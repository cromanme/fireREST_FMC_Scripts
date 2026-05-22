#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_deployabledevices_id_pendingchanges.py

Connects to a Cisco FMC, resolves an FTD device by hostname, and retrieves
its pending deployment changes, saving the result to a JSON file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_HOSTNAME to the name of the target device.

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

OUTPUT_FILE: str  = "deployabledevices_id_pendingchanges.json"
FTD_HOSTNAME: str = "404rpvQROfpr1150-02"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve pending deployment changes for a specific FTD and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        ftd_info = fmc.device.devicerecord.get(name=FTD_HOSTNAME)
        ftd_uuid = ftd_info["id"]
    except Exception:
        logger.exception("Failed to resolve device UUID for '%s'.", FTD_HOSTNAME)
        raise SystemExit(1)

    try:
        response = fmc.deployment.deployabledevices.pendingchanges.get(
            container_uuid=ftd_uuid
        )
    except Exception:
        logger.exception(
            "Failed to retrieve pending changes for device '%s'.", FTD_HOSTNAME
        )
        raise SystemExit(1)

    if not response:
        logger.warning("No pending changes found for device '%s'.", FTD_HOSTNAME)
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
