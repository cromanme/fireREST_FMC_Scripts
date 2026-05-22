#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_subinterfaces_from_csv.py

Connects to a Cisco FMC and creates subinterfaces on the specified FTD
device using definitions read from a JSON file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_UUID to the target device and JSON_FILENAME to the source file.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

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

# Target FTD device UUID
FTD_UUID: str = "b155923e-db11-11ee-8794-be48d41fc879"

# JSON file containing subinterface definitions
JSON_FILENAME: str = "ftd_interfaces.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_subinterface(fmc, ftd_uuid: str, payload: dict) -> bool:
    """
    Create a single subinterface on the specified FTD device.

    Args:
        fmc: Authenticated FMC client instance.
        ftd_uuid (str): UUID of the target FTD device.
        payload (dict): Subinterface definition to POST.

    Returns:
        bool: True if the subinterface was created successfully, False otherwise.
    """
    name     = payload.get("ifname", payload.get("name", "N/A"))
    vlan_id  = payload.get("vlanId", "N/A")

    try:
        response = fmc.device.devicerecord.subinterface.create(
            data=payload,
            container_uuid=ftd_uuid,
        )

        if response.status_code == 201:
            logger.info("Created subinterface '%s' (VLAN %s).", name, vlan_id)
            return True

        logger.warning(
            "Unexpected response creating subinterface '%s': %s",
            name, response.headers,
        )
        return False

    except Exception as e:
        logger.error("Failed to create subinterface '%s': %s", name, e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Load subinterface definitions from JSON and create them on the target FTD.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    subinterfaces: List[dict] = utils.load_routes_from_json(JSON_FILENAME)
    if not subinterfaces:
        logger.warning("No subinterface definitions found in '%s'. Nothing to do.", JSON_FILENAME)
        raise SystemExit(0)

    created: int = 0
    failed:  int = 0

    for payload in subinterfaces.values():
        if create_subinterface(fmc, FTD_UUID, payload):
            created += 1
        else:
            failed += 1

    logger.info("Done. Created: %d | Failed: %d.", created, failed)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
