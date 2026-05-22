#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_virtualrouter.py

Connects to a Cisco FMC and creates a Virtual Router on a specific FTD
device with a predefined set of subinterfaces.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Update FTD_UUID, VR_NAME, and VR_INTERFACES to match the target
    deployment before running.

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

FTD_UUID: str  = "b155923e-db11-11ee-8794-be48d41fc879"
VR_NAME: str   = "PITA"

VR_INTERFACES: List[Dict] = [
    {
        "ifname": "Pita_Inside",
        "type":   "SubInterface",
        "id":     "00DF1D35-F0FA-0ed3-0000-098784264321",
        "name":   "Ethernet1/1.3006",
    },
    {
        "ifname": "Outside_vlan61",
        "type":   "SubInterface",
        "id":     "00DF1D35-F0FA-0ed3-0000-098784264192",
        "name":   "Ethernet1/2.61",
    },
    {
        "ifname": "Outside_vlan703",
        "type":   "SubInterface",
        "id":     "00DF1D35-F0FA-0ed3-0000-098784264235",
        "name":   "Ethernet1/2.703",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_virtualrouter_payload(name: str, interfaces: List[Dict]) -> Dict:
    """
    Build the Virtual Router creation payload.

    Args:
        name (str): Name to assign to the Virtual Router.
        interfaces (List[Dict]): List of interface references to attach.

    Returns:
        Dict: Payload ready to POST to the FMC API.
    """
    return {
        "name":       name,
        "type":       "VirtualRouter",
        "interfaces": interfaces,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Create a Virtual Router on the target FTD device."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    payload = build_virtualrouter_payload(VR_NAME, VR_INTERFACES)
    logger.info("Creating Virtual Router '%s' on device '%s'.", VR_NAME, FTD_UUID)

    try:
        fmc.device.devicerecord.routing.virtualrouter.create(
            container_uuid=FTD_UUID,
            data=payload,
        )
        logger.info("Virtual Router '%s' created successfully.", VR_NAME)
    except Exception:
        logger.exception(
            "Failed to create Virtual Router '%s' on device '%s'.", VR_NAME, FTD_UUID
        )
        raise SystemExit(1)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
