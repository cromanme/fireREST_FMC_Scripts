#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_virtualrouter.py

Connects to a Cisco FMC and retrieves all Virtual Routers for a specific
FTD device, saving the result to a JSON file.

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

OUTPUT_FILE: str = "ftd_virtualrouter.json"
FTD_UUID: str    = "6ffc03be-ab31-11ee-a3e6-c1dec40da4f6"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve Virtual Routers for an FTD device from FMC and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.device.devicerecord.routing.virtualrouter.get(
            container_uuid=FTD_UUID
        )
    except Exception:
        logger.exception(
            "Failed to retrieve Virtual Routers for device '%s'.", FTD_UUID
        )
        raise SystemExit(1)

    if not response:
        logger.warning("No Virtual Routers found for device '%s'.", FTD_UUID)
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
