#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_device_by_name.py

Connects to a Cisco FMC, retrieves a registered device by name, and saves
the result to a JSON file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_NAME to the hostname of the device to look up.

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

OUTPUT_FILE: str = "device_by_name.json"
FTD_NAME: str    = "ftd01"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve a device by name from FMC and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.device.devicerecord.get(name=FTD_NAME, expand=True)
    except Exception:
        logger.exception("Failed to retrieve device '%s' from FMC.", FTD_NAME)
        raise SystemExit(1)

    if not response:
        logger.warning("Device '%s' not found in FMC.", FTD_NAME)
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
