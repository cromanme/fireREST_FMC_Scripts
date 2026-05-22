#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
delete_ipv4_static_routes_from_csv.py

Connects to a Cisco FMC, reads a CSV file containing route UUIDs, and
deletes each matching IPv4 static route from the specified FTD device.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_UUID to the target device and CSV_FILENAME to the UUID list.

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
from typing import List

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

# Device to delete static routes from
FTD_UUID: str = "b9acf5dc-896c-11ed-a7a5-db13f6c0ea82"

# CSV file containing route UUIDs to delete (one UUID per row, no header)
CSV_FILENAME: str = "RutasDelete.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def delete_ipv4_static_route(fmc, route_id: str, ftd_uuid: str) -> bool:
    """
    Delete a single IPv4 static route from the specified FTD device.

    Args:
        fmc: Authenticated FMC client instance.
        route_id (str): UUID of the static route to delete.
        ftd_uuid (str): UUID of the FTD device.

    Returns:
        bool: True if deletion was successful, False otherwise.
    """
    try:
        response = fmc.device.devicerecord.routing.ipv4staticroute.delete(
            container_uuid=ftd_uuid,
            uuid=route_id,
        )

        if response.status_code == 200:
            logger.info("Deleted static route '%s' from '%s'.", route_id, ftd_uuid)
            return True

        logger.warning(
            "Unexpected response deleting route '%s': %s", route_id, response.text
        )
        return False

    except Exception as e:
        logger.error("Failed to delete static route '%s': %s", route_id, e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Read route UUIDs from a CSV file and delete each IPv4 static route
    from the target FTD device.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    route_uuids: List[str] = utils.load_uuids_from_csv(CSV_FILENAME)
    if not route_uuids:
        logger.warning("No UUIDs found in '%s'. Nothing to do.", CSV_FILENAME)
        raise SystemExit(0)

    deleted: int = 0
    failed:  int = 0

    for route_id in route_uuids:
        if delete_ipv4_static_route(fmc, route_id, FTD_UUID):
            deleted += 1
        else:
            failed += 1

    logger.info("Done. Deleted: %d | Failed: %d.", deleted, failed)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
