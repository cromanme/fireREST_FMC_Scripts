#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_ipv4static_routes_from_csv_and_json.py

Connects to a Cisco FMC, reads a CSV file containing route UUIDs, looks up
each UUID in a local JSON backup file, builds the required payload, and
creates the corresponding IPv4 static routes on the target FTD.

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

# Target FTD device to create static routes on
FTD_UUID: str = "b9acf5dc-896c-11ed-a7a5-db13f6c0ea82"

# CSV file containing route UUIDs to restore (one UUID per row, no header)
CSV_FILENAME: str = "RutasDelete.csv"

# JSON backup file produced by get_ipv4_static_route.py
JSON_FILENAME: str = "ftd_ipv4_static_route.json"


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


def create_ipv4_static_route(fmc, ftd_uuid: str, payload: dict) -> bool:
    """
    POST a single IPv4 static route to the specified FTD device.

    Args:
        fmc: Authenticated FMC client instance.
        ftd_uuid (str): UUID of the target FTD device.
        payload (dict): Route payload to POST.

    Returns:
        bool: True if the route was created successfully, False otherwise.
    """
    interface = payload.get("interfaceName", "N/A")
    networks  = [n.get("name", "N/A") for n in payload.get("selectedNetworks", [])]
    gateway   = payload.get("gateway", {}).get("object", {}).get("name", "N/A")

    try:
        response = fmc.device.devicerecord.routing.ipv4staticroute.create(
            container_uuid=ftd_uuid,
            data=payload,
        )

        if response.status_code == 201:
            logger.info(
                "Created route: interface='%s', networks=%s, gateway='%s'.",
                interface, networks, gateway,
            )
            return True

        logger.warning(
            "Unexpected response creating route: interface='%s', networks=%s, "
            "gateway='%s'. Response: %s",
            interface, networks, gateway, response,
        )
        return False

    except Exception as e:
        logger.error(
            "Failed to create route: interface='%s', networks=%s, gateway='%s'. Error: %s",
            interface, networks, gateway, e,
        )
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    1. Load route UUIDs from the CSV file.
    2. Load route definitions from the JSON backup.
    3. Match each UUID to its route definition.
    4. Build a creation payload and POST it to the target FTD.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    route_uuids: List[str] = utils.load_uuids_from_csv(CSV_FILENAME)
    if not route_uuids:
        logger.warning("No UUIDs found in '%s'. Nothing to do.", CSV_FILENAME)
        raise SystemExit(0)

    routes_by_uuid: Dict[str, dict] = utils.load_routes_from_json(JSON_FILENAME)

    created: int = 0
    skipped: int = 0
    failed:  int = 0

    for uuid in route_uuids:
        route = routes_by_uuid.get(uuid)
        if not route:
            logger.warning("UUID '%s' not found in '%s'. Skipping.", uuid, JSON_FILENAME)
            skipped += 1
            continue

        payload = build_route_payload(route)
        if create_ipv4_static_route(fmc, FTD_UUID, payload):
            created += 1
        else:
            failed += 1

    logger.info(
        "Done. Created: %d | Skipped (not in JSON): %d | Failed: %d.",
        created, skipped, failed,
    )

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
