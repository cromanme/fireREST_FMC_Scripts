#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_physical_interfaces.py

Connects to a Cisco FMC and retrieves the physical interfaces for a specific
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

OUTPUT_FILE: str = "../Responses/ftd_physical_interfaces.json"
FTD_UUID: str    = "9ae3a6ec-1bc1-11f1-8a05-a2d0586ee85a"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve physical interfaces for an FTD device from FMC and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.device.devicerecord.physicalinterface.get(container_uuid=FTD_UUID)
    except Exception:
        logger.exception(
            "Failed to retrieve physical interfaces for device '%s'.", FTD_UUID
        )
        raise SystemExit(1)

    if not response:
        logger.warning("No physical interfaces found for device '%s'.", FTD_UUID)
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
