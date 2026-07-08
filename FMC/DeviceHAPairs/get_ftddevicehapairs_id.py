#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_ftddevicehapairs_id.py

Connects to a Cisco FMC and retrieves a specific FTD HA pair by UUID,
saving the result to a JSON file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set HA_UUID to the UUID of the HA pair to retrieve.

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

OUTPUT_FILE: str = "../Responses/ftd_device_ha_id.json"
HA_UUID: str = "e2238484-0582-11ef-8562-cc0ea2e7ab0d"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve a specific FTD HA pair by UUID from FMC and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.devicehapair.ftdhapair.get(uuid=HA_UUID)
    except Exception:
        logger.exception("Failed to retrieve FTD HA pair '%s' from FMC.", HA_UUID)
        raise SystemExit(1)

    if not response:
        logger.warning("No FTD HA pair found for UUID '%s'.", HA_UUID)
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
