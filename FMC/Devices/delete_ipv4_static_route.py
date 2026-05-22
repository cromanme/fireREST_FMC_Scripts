#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
delete_ipv4_static_route.py

Connects to a Cisco FMC, backs up all IPv4 static routes for a specific FTD
device to a CSV file, then deletes them all.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_UUID to the UUID of the target FTD device.

Output CSV columns:
    UUID, Interface, Selected Networks, Gateway, Metric

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

FTD_UUID: str    = "8f7eaff4-e3ff-11ef-aeb1-d4b3c2f8f758"
CSV_FILENAME: str = "ftd_ipv4_static_routes_backup.csv"

CSV_FIELDNAMES: List[str] = [
    "UUID", "Interface", "Selected Networks", "Gateway", "Metric"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_ipv4_static_routes(fmc, ftd_uuid: str) -> List[Dict]:
    """
    Retrieve all IPv4 static routes from the specified FTD device.

    Args:
        fmc: Authenticated FMC client instance.
        ftd_uuid (str): UUID of the target FTD device.

    Returns:
        List[Dict]: Route definitions, or an empty list on failure.
    """
    try:
        return fmc.device.devicerecord.routing.ipv4staticroute.get(
            container_uuid=ftd_uuid
        ) or []
    except Exception:
        logger.exception(
            "Failed to retrieve IPv4 static routes for device '%s'.", ftd_uuid
        )
        return []


def backup_routes_to_csv(routes: List[Dict], filepath: str) -> None:
    """
    Write a CSV backup of the given routes.

    Args:
        routes (List[Dict]): Route definitions from the FMC API.
        filepath (str): Destination CSV file path.
    """
    rows = [
        {
            "UUID":              r.get("id", "N/A"),
            "Interface":         r.get("interfaceName", "N/A"),
            "Selected Networks": r.get("selectedNetworks", "N/A"),
            "Gateway":           r.get("gateway", {}).get("object", {}).get("name", "N/A"),
            "Metric":            r.get("metricValue", "N/A"),
        }
        for r in routes
    ]
    utils.write_csv(filepath, rows, CSV_FIELDNAMES)


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
            logger.info("Deleted static route '%s'.", route_id)
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
    Back up all IPv4 static routes on the target FTD to CSV, then delete them.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    routes = get_ipv4_static_routes(fmc, FTD_UUID)
    if not routes:
        logger.warning(
            "No IPv4 static routes found for device '%s'. Nothing to do.", FTD_UUID
        )
        fmc.conn.session.close()
        return

    backup_routes_to_csv(routes, CSV_FILENAME)
    logger.info("Backed up %d route(s) to '%s'.", len(routes), CSV_FILENAME)

    deleted: int = 0
    failed:  int = 0

    for route in routes:
        route_id = route.get("id")
        if not route_id:
            continue
        if delete_ipv4_static_route(fmc, route_id, FTD_UUID):
            deleted += 1
        else:
            failed += 1

    logger.info("Done. Deleted: %d | Failed: %d.", deleted, failed)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
