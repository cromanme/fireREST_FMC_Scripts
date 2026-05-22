#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_ospfinterface_global.py

Connects to a Cisco FMC and retrieves the OSPF interface configuration for
the global routing context of a specific FTD device, saving the result to
a JSON file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_UUID to the UUID of the target FTD device.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging

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

OUTPUT_FILE: str = "ftd_ospfinterface_global.json"
FTD_UUID: str    = "e9ef0f60-1c20-11ec-a008-deb05a5da02d"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve global OSPF interface config for an FTD device and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.device.devicerecord.routing.ospfinterface.get(
            container_uuid=FTD_UUID
        )
    except Exception:
        logger.exception(
            "Failed to retrieve OSPF interface config for device '%s'.", FTD_UUID
        )
        raise SystemExit(1)

    if not response:
        logger.warning(
            "No OSPF interface config found for device '%s'.", FTD_UUID
        )
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
