#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_ipv4_static_routes_to_csv.py

Connects to a Cisco FMC and retrieves all IPv4 static routes for a specific
FTD device, saving the result to a CSV file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_UUID to the UUID of the target FTD device.

Output CSV columns:
    Route_UUID, Interface, Gateway, Selected Networks, Metric

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

OUTPUT_FILE: str = "../Responses/ftd_ipv4_static_routes.csv"
FTD_UUID: str    = "16459cd4-43dd-11ed-95c6-d99a1057aa23"

CSV_FIELDNAMES: List[str] = [
    "VRF","Route_UUID", "Interface", "Gateway", "Selected Networks", "Metric"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def routes_to_rows(routes: List[Dict]) -> List[Dict]:
    """
    Convert a list of FMC route dicts to CSV-ready row dicts.

    Args:
        routes (List[Dict]): Route definitions from the FMC API.

    Returns:
        List[Dict]: Rows keyed by CSV_FIELDNAMES.
    """
    return [
        {
            "VRF":               route.get("egressInterfaceVirtualRouter", "Global"),
            "Route_UUID":        route.get("id", "N/A"),
            "Interface":         route.get("interfaceName", "N/A"),
            "Gateway":           route.get("gateway", {}).get("object", {}).get("name", "N/A"),
            "Selected Networks": route.get("selectedNetworks", "N/A"),
            "Metric":            route.get("metricValue", "N/A"),
        }
        for route in routes
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve IPv4 static routes from an FTD device and export to CSV."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        routes = fmc.device.devicerecord.routing.ipv4staticroute.get(
            container_uuid=FTD_UUID
        )
    except Exception:
        logger.exception("Failed to retrieve IPv4 static routes for device '%s'.", FTD_UUID)
        raise SystemExit(1)

    if not routes:
        logger.warning("No IPv4 static routes found for device '%s'.", FTD_UUID)
        raise SystemExit(0)

    rows = routes_to_rows(routes)
    utils.write_csv(OUTPUT_FILE, rows, CSV_FIELDNAMES)
    logger.info("Saved %d route(s) to '%s'.", len(rows), OUTPUT_FILE)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
