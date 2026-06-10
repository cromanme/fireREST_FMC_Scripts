#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_ipv4static_routes_from_csv_and_json.py

Connects to a Cisco FMC, reads a CSV file containing route UUIDs, looks up
each UUID in a local JSON backup file, builds the required payloads, and
creates the corresponding IPv4 static routes on the target FTD in bulk.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    A valid FTD UUID, a CSV file with route UUIDs, and a JSON backup
    file with the route definitions must be provided.

CSV Format (no header row, one UUID per line):
    005056A1-C63D-0ed3-0000-008590048076
    005056A1-C63D-0ed3-0000-008590048179
    ...

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
from typing import Dict, List

import utils

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FTD_UUID: str        = "b9acf5dc-896c-11ed-a7a5-db13f6c0ea82"  # target FTD device
CSV_FILENAME: str    = "RutasDelete.csv"                       # route UUIDs (one per row, no header)
JSON_FILENAME: str   = "ftd_ipv4_static_route.json"            # JSON backup from get_ipv4_static_route.py
BULK_CHUNK_SIZE: int = 1000                                    # max routes per bulk API request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_route_payload(route: dict) -> dict:
    """
    Build a creation payload from a route definition in the JSON backup.

    Strips server-managed fields (id, metadata, links) that must not be
    included when POSTing a new route.

    Args:
        route (dict): Full route definition from the JSON backup.

    Returns:
        dict: Payload ready to be sent to the FMC API.
    """
    return {
        "type": route.get("type", "IPv4StaticRoute"),
        "interfaceName": route["interfaceName"],
        "selectedNetworks": route["selectedNetworks"],
        "gateway": route["gateway"],
        "metricValue": route.get("metricValue", 1),
        "isTunneled": route.get("isTunneled", False),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    1. Load route UUIDs from the CSV file.
    2. Load route definitions from the JSON backup.
    3. Match each UUID to its route definition and build a creation payload.
    4. Bulk POST all payloads to the target FTD in chunks.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    route_uuids: List[str] = utils.load_uuids_from_csv(CSV_FILENAME)
    if not route_uuids:
        logger.warning("No UUIDs found in '%s'. Nothing to do.", CSV_FILENAME)
        raise SystemExit(0)

    routes_by_uuid: Dict[str, dict] = utils.load_routes_from_json(JSON_FILENAME)

    payloads: List[dict] = []
    skipped: int = 0

    for uuid in route_uuids:
        route = routes_by_uuid.get(uuid)
        if not route:
            logger.warning("UUID '%s' not found in '%s'. Skipping.", uuid, JSON_FILENAME)
            skipped += 1
            continue

        payloads.append(build_route_payload(route))

    if not payloads:
        logger.warning("No valid route payloads to create. Skipped: %d.", skipped)
        fmc.conn.session.close()
        return

    logger.info(
        "Prepared %d route payload(s) for bulk creation. Skipped: %d.",
        len(payloads), skipped,
    )

    created: int = 0
    failed:  int = 0

    for i in range(0, len(payloads), BULK_CHUNK_SIZE):
        chunk = payloads[i : i + BULK_CHUNK_SIZE]
        logger.info(
            "Bulk creating routes %d–%d of %d ...",
            i + 1, i + len(chunk), len(payloads),
        )
        try:
            # Passing a list triggers ?bulk=true automatically in fireREST
            response = fmc.device.devicerecord.routing.ipv4staticroute.create(
                data=chunk,
                container_uuid=FTD_UUID,
            )
            if response.status_code in (200, 201):
                created += len(chunk)
                logger.info("Bulk created %d route(s) successfully.", len(chunk))
            else:
                failed += len(chunk)
                logger.error(
                    "Bulk create failed (HTTP %d): %s",
                    response.status_code,
                    response.text[:500],
                )
        except Exception:
            failed += len(chunk)
            logger.exception("Bulk create request failed for chunk of %d routes.", len(chunk))

    logger.info(
        "Done. Created: %d | Skipped (not in JSON): %d | Failed: %d.",
        created, skipped, failed,
    )

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
