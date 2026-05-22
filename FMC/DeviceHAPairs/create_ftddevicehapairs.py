#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_ftddevicehapairs.py

Connects to a Cisco FMC and creates an FTD HA pair from two existing
registered devices, using Ethernet1/8 as the failover interface.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Update FTD_PRI_HOSTNAME, FTD_SEC_HOSTNAME, SITE_ID, and LOCATION
    to match the target deployment before running.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
from typing import Dict

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

OUTPUT_FILE: str = "ftd_device_ha_pairs.json"
FTD_PRI_HOSTNAME: str = "FTD-01"
FTD_SEC_HOSTNAME: str = "FTD-02"


# Failover interface — index 7 = Ethernet1/8 (0-based list from physicalinterface.get)
FAILOVER_INTERFACE_INDEX: int = 7
FAILOVER_INTERFACE_NAME: str  = "Ethernet1/8"

# Failover link IP addresses
LAN_ACTIVE_IP: str   = "1.1.1.1"
LAN_STANDBY_IP: str  = "1.1.1.2"
LAN_SUBNET_MASK: str = "255.255.255.252"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_ha_payload(
    pri_uuid: str,
    sec_uuid: str,
    eth8_uuid: str,
    ha_name: str,
) -> Dict:
    """
    Build the FTD HA pair creation payload.

    Args:
        pri_uuid (str): UUID of the primary FTD device.
        sec_uuid (str): UUID of the secondary FTD device.
        eth8_uuid (str): UUID of the failover physical interface.
        ha_name (str): Name to assign to the HA pair.

    Returns:
        Dict: Payload ready to POST to the FMC API.
    """
    failover_interface = {
        "id":   eth8_uuid,
        "type": "PhysicalInterface",
        "name": FAILOVER_INTERFACE_NAME,
    }
    failover_link = {
        "useIPv6Address": "false",
        "subnetMask":     LAN_SUBNET_MASK,
        "activeIP":       LAN_ACTIVE_IP,
        "standbyIP":      LAN_STANDBY_IP,
        "logicalName":    "Failover",
        "interfaceObject": failover_interface,
    }
    return {
        "primary":   {"id": pri_uuid},
        "secondary": {"id": sec_uuid},
        "name":      ha_name,
        "type":      "DeviceHAPair",
        "ftdHABootstrap": {
            "isEncryptionEnabled":    "false",
            "useSameLinkForFailovers": "true",
            "lanFailover":     failover_link,
            "statefulFailover": failover_link,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Look up the primary and secondary FTD devices, resolve the failover
    interface UUID, then create the HA pair on FMC.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    # Resolve device UUIDs by hostname
    try:
        pri_info = fmc.device.devicerecord.get(name=FTD_PRI_HOSTNAME)
        pri_uuid = pri_info["id"]
        sec_info = fmc.device.devicerecord.get(name=FTD_SEC_HOSTNAME)
        sec_uuid = sec_info["id"]
    except Exception:
        logger.exception("Failed to resolve device UUIDs from FMC.")
        raise SystemExit(1)

    # Resolve failover interface UUID from primary device
    try:
        interfaces = fmc.device.devicerecord.physicalinterface.get(container_uuid=pri_uuid)
        eth8_uuid  = interfaces[FAILOVER_INTERFACE_INDEX]["id"]
    except Exception:
        logger.exception(
            "Failed to retrieve physical interfaces for device '%s'.", FTD_PRI_HOSTNAME
        )
        raise SystemExit(1)

    ha_name = "FTD-HA"
    payload  = build_ha_payload(pri_uuid, sec_uuid, eth8_uuid, ha_name)

    logger.info("Creating FTD HA pair '%s'.", ha_name)
    try:
        response = fmc.devicehapair.ftdhapair.create(data=payload)
    except Exception:
        logger.exception("Failed to create FTD HA pair '%s'.", ha_name)
        raise SystemExit(1)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)
    logger.info("FTD HA pair '%s' created successfully.", ha_name)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
