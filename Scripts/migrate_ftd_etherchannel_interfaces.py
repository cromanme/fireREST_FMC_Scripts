#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_ftd_etherchannel_interfaces.py

Connects to a single FMC, reads all EtherChannel interfaces from a source FTD,
and recreates them on a target FTD within the same FMC.

Physical interface references in selectedInterfaces are re-mapped by name:
source physical interface UUIDs are replaced with the corresponding destination
FTD physical interface UUIDs so the EtherChannel membership is preserved.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set SRC_FTD_UUID and DST_FTD_UUID to the source and target device UUIDs.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Note:
    For devices in HA/Cluster, use the UUID of the Active/Control unit.
    EtherChannel IDs (etherChannelId) must not already exist on the destination FTD.
    Security zones are referenced by UUID — both FTDs must share the same FMC domain.

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

SRC_FTD_UUID: str = "REPLACE_WITH_SOURCE_FTD_UUID"
DST_FTD_UUID: str = "REPLACE_WITH_DESTINATION_FTD_UUID"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_physical_interface_map(fmc, device_uuid: str) -> Dict[str, str]:
    """
    Fetch all physical interfaces on *device_uuid* and return a name→UUID map.

    Used to remap selectedInterfaces from source to destination UUIDs.

    Args:
        fmc: Authenticated FMC client instance.
        device_uuid (str): UUID of the FTD device.

    Returns:
        Dict[str, str]: Mapping of interface name to UUID (empty on failure).
    """
    try:
        interfaces = fmc.device.devicerecord.physicalinterface.get(
            container_uuid=device_uuid
        )
    except Exception:
        logger.exception(
            "Failed to retrieve physical interfaces for device %s.", device_uuid
        )
        return {}

    if not interfaces:
        logger.warning("No physical interfaces found for device %s.", device_uuid)
        return {}

    if isinstance(interfaces, dict):
        interfaces = [interfaces]

    mapping: Dict[str, str] = {
        iface["name"]: iface["id"]
        for iface in interfaces
        if "name" in iface and "id" in iface
    }
    logger.info(
        "Retrieved %d physical interface(s) for device %s.", len(mapping), device_uuid
    )
    return mapping


def _remap_selected_interfaces(
    selected_interfaces: List[Dict],
    dst_iface_map: Dict[str, str],
) -> Optional[List[Dict]]:
    """
    Replace source physical interface UUIDs with destination UUIDs matched by name.

    Returns None if any interface name cannot be resolved on the destination device,
    preventing a misconfigured EtherChannel from being created.

    Args:
        selected_interfaces (List[Dict]): selectedInterfaces from the source GET response.
        dst_iface_map (Dict[str, str]): name→UUID map for the destination FTD.

    Returns:
        Optional[List[Dict]]: Remapped list, or None if any lookup fails.
    """
    remapped: List[Dict] = []
    for iface in selected_interfaces:
        name = iface.get("name", "")
        dst_uuid = dst_iface_map.get(name)
        if dst_uuid is None:
            logger.error(
                "Physical interface '%s' not found on destination FTD — "
                "cannot remap selectedInterfaces.",
                name,
            )
            return None
        remapped.append({
            "type": iface.get("type", "PhysicalInterface"),
            "name": name,
            "id":   dst_uuid,
        })
    return remapped


def etherchannel_payload(
    intf: Dict,
    dst_iface_map: Dict[str, str],
) -> Optional[Dict]:
    """
    Build a minimal POST payload from a source EtherChannel interface dict.

    Strips GET-response-only fields (links, metadata, id, name) and remaps
    selectedInterfaces UUIDs to match the destination FTD's physical interfaces.

    Args:
        intf (Dict): EtherChannel interface as returned by the FMC GET API.
        dst_iface_map (Dict[str, str]): name→UUID map for the destination FTD.

    Returns:
        Optional[Dict]: Payload for POST to FMC, or None when selectedInterfaces
        cannot be fully remapped.
    """
    selected = _remap_selected_interfaces(
        intf.get("selectedInterfaces", []), dst_iface_map
    )
    if selected is None:
        return None

    payload: Dict = {
        "type":                       "EtherChannelInterface",
        "etherChannelId":             intf["etherChannelId"],
        "mode":                       intf.get("mode", "NONE"),
        "lacpMode":                   intf.get("lacpMode", "ACTIVE"),
        "lacpRate":                   intf.get("lacpRate", "DEFAULT"),
        "maxActivePhysicalInterface": intf.get("maxActivePhysicalInterface", 8),
        "minActivePhysicalInterface": intf.get("minActivePhysicalInterface", 1),
        "selectedInterfaces":         selected,
        "enabled":                    intf.get("enabled", True),
        "MTU":                        intf.get("MTU", 1500),
        "managementOnly":             intf.get("managementOnly", False),
        "nveOnly":                    intf.get("nveOnly", False),
        "enableAntiSpoofing":         intf.get("enableAntiSpoofing", False),
        "enableSGTPropagate":         intf.get("enableSGTPropagate", False),
    }

    # Scalar optional fields
    for key in ("loadBalancing", "priority", "ifname"):
        if key in intf:
            payload[key] = intf[key]

    # Structured optional fields — passed through as-is; securityZone UUID is
    # stable across devices on the same FMC domain.
    for key in (
        "hardware",
        "LLDP",
        "ipv4",
        "ipv6",
        "securityZone",
        "pathMonitoring",
        "applicationMonitoring",
        "overrideDefaultFragmentSetting",
    ):
        if key in intf:
            payload[key] = intf[key]

    return payload


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Read EtherChannel interfaces from the source FTD and recreate them on the
    target FTD, remapping physical interface UUIDs by interface name.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    logger.info(
        "Retrieving physical interfaces from destination FTD: %s", DST_FTD_UUID
    )
    dst_iface_map = _get_physical_interface_map(fmc, DST_FTD_UUID)
    if not dst_iface_map:
        logger.error("Cannot proceed without a destination physical interface map.")
        fmc.conn.session.close()
        raise SystemExit(1)

    logger.info(
        "Retrieving EtherChannel interfaces from source FTD: %s", SRC_FTD_UUID
    )
    try:
        interfaces = fmc.device.devicerecord.etherchannelinterface.get(
            container_uuid=SRC_FTD_UUID
        )
    except Exception:
        logger.exception("Failed to retrieve EtherChannel interfaces.")
        fmc.conn.session.close()
        raise SystemExit(1)

    if not interfaces:
        logger.warning(
            "No EtherChannel interfaces found on source FTD %s.", SRC_FTD_UUID
        )
        fmc.conn.session.close()
        return

    if isinstance(interfaces, dict):
        interfaces = [interfaces]

    logger.info("Found %d EtherChannel interface(s) on source FTD.", len(interfaces))

    created: int = 0
    skipped: int = 0
    failed:  int = 0

    for intf in interfaces:
        intf_label = intf.get(
            "name", f"Port-channel{intf.get('etherChannelId', '?')}"
        )
        logger.info(
            "Processing: %s (etherChannelId=%s, ifname=%s)",
            intf_label,
            intf.get("etherChannelId"),
            intf.get("ifname", "<none>"),
        )

        payload = etherchannel_payload(intf, dst_iface_map)
        if payload is None:
            logger.warning(
                "Skipping %s — could not remap all selectedInterfaces.", intf_label
            )
            skipped += 1
            continue

        try:
            response = fmc.device.devicerecord.etherchannelinterface.create(
                data=payload,
                container_uuid=DST_FTD_UUID,
            )
            if response.status_code in (200, 201, 202):
                created += 1
                logger.info("Created %s successfully.", intf_label)
            else:
                failed += 1
                logger.error(
                    "Failed to create %s (HTTP %d): %s",
                    intf_label,
                    response.status_code,
                    response.text[:500],
                )
        except Exception:
            failed += 1
            logger.exception("Request failed for %s.", intf_label)

    logger.info(
        "Done. Created: %d | Skipped: %d | Failed: %d.", created, skipped, failed
    )

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
