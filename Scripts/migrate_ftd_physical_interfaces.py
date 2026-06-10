#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_ftd_physical_interfaces.py

Connects to a single FMC, reads the configuration of all physical interfaces
from a source FTD, and applies it to the matching physical interfaces on a
target FTD within the same FMC.

Physical interfaces are matched by name (e.g. GigabitEthernet1/1). Because
physical interfaces are hardware-native — they cannot be created via API —
this script uses PUT (update) rather than POST. Interfaces that exist on the
source but are absent on the destination are logged and skipped.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set SRC_FTD_UUID and DST_FTD_UUID to the source and target device UUIDs.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Note:
    For devices in HA/Cluster, use the UUID of the Active/Control unit.
    Security zones are referenced by UUID — both FTDs must share the same
    FMC domain so that zone UUIDs remain valid on the destination device.

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

def _get_interfaces(fmc, device_uuid: str) -> List[Dict]:
    """
    Retrieve all physical interfaces for *device_uuid* with full detail.

    The fireREST client appends ?expanded=true automatically when the library
    version supports it; if the returned items lack config fields the caller
    will perform a per-interface GET to hydrate them.

    Args:
        fmc: Authenticated FMC client instance.
        device_uuid (str): UUID of the FTD device.

    Returns:
        List[Dict]: List of physical interface dicts (may be minimal stubs).

    Raises:
        SystemExit: If the API call fails entirely.
    """
    try:
        result = fmc.device.devicerecord.physicalinterface.get(
            container_uuid=device_uuid
        )
    except Exception:
        logger.exception(
            "Failed to retrieve physical interfaces for device %s.", device_uuid
        )
        raise SystemExit(1)

    if not result:
        return []

    if isinstance(result, dict):
        result = [result]

    return result


def _hydrate_interface(fmc, device_uuid: str, intf_uuid: str) -> Optional[Dict]:
    """
    Fetch the full detail of a single physical interface by UUID.

    Used when the GET-all response returns only stub objects (name + id only),
    which happens when the FMC version does not honour the expanded parameter
    via the fireREST library call.

    Args:
        fmc: Authenticated FMC client instance.
        device_uuid (str): UUID of the FTD device.
        intf_uuid (str): UUID of the physical interface.

    Returns:
        Optional[Dict]: Full interface dict, or None on failure.
    """
    try:
        return fmc.device.devicerecord.physicalinterface.get(
            container_uuid=device_uuid,
            uuid=intf_uuid,
        )
    except Exception:
        logger.exception(
            "Failed to hydrate interface %s on device %s.", intf_uuid, device_uuid
        )
        return None


def _build_name_map(interfaces: List[Dict]) -> Dict[str, Dict]:
    """
    Index a list of interface dicts by interface name.

    Args:
        interfaces (List[Dict]): Interfaces as returned by _get_interfaces.

    Returns:
        Dict[str, Dict]: Mapping of interface name to interface dict.
    """
    return {
        intf["name"]: intf
        for intf in interfaces
        if "name" in intf
    }


# Fields present in a GET response that must not be sent in a PUT body.
_READONLY_FIELDS = frozenset({"links", "metadata"})


def physical_interface_payload(src_intf: Dict, dst_intf: Dict) -> Dict:
    """
    Build a PUT payload by merging source configuration onto the destination.

    The destination's ``id`` and ``name`` are preserved so the PUT targets
    the correct hardware slot. All logical configuration (mode, IP, zone,
    hardware settings, etc.) is taken from the source interface.

    Args:
        src_intf (Dict): Source physical interface from the GET response.
        dst_intf (Dict): Destination physical interface stub (name + id).

    Returns:
        Dict: Payload ready for PUT to the FMC API.
    """
    payload: Dict = {
        "type": "PhysicalInterface",
        "id":   dst_intf["id"],
        "name": dst_intf["name"],
    }

    # Copy all configurable fields from the source, skip read-only fields and
    # identity keys that must come from the destination.
    for key, value in src_intf.items():
        if key in _READONLY_FIELDS or key in ("id", "name", "type"):
            continue
        payload[key] = value

    return payload


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Read physical interface configurations from the source FTD and apply them
    to identically-named interfaces on the destination FTD via PUT.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    # -----------------------------------------------------------------------
    # Fetch source interfaces with full detail
    # -----------------------------------------------------------------------
    logger.info(
        "Retrieving physical interfaces from source FTD: %s", SRC_FTD_UUID
    )
    src_interfaces = _get_interfaces(fmc, SRC_FTD_UUID)

    if not src_interfaces:
        logger.warning(
            "No physical interfaces found on source FTD %s.", SRC_FTD_UUID
        )
        fmc.conn.session.close()
        return

    # Hydrate stubs that only contain name + id (no config fields)
    hydrated_src: List[Dict] = []
    for intf in src_interfaces:
        if "mode" not in intf and "enabled" not in intf:
            logger.debug(
                "Hydrating stub interface '%s' from source FTD.", intf.get("name")
            )
            full = _hydrate_interface(fmc, SRC_FTD_UUID, intf["id"])
            if full:
                hydrated_src.append(full)
        else:
            hydrated_src.append(intf)

    logger.info(
        "Source FTD has %d physical interface(s).", len(hydrated_src)
    )

    # -----------------------------------------------------------------------
    # Fetch destination interfaces to build name → UUID map
    # -----------------------------------------------------------------------
    logger.info(
        "Retrieving physical interfaces from destination FTD: %s", DST_FTD_UUID
    )
    dst_interfaces = _get_interfaces(fmc, DST_FTD_UUID)

    if not dst_interfaces:
        logger.error(
            "No physical interfaces found on destination FTD %s. Cannot proceed.",
            DST_FTD_UUID,
        )
        fmc.conn.session.close()
        raise SystemExit(1)

    dst_map: Dict[str, Dict] = _build_name_map(dst_interfaces)
    logger.info(
        "Destination FTD has %d physical interface(s).", len(dst_map)
    )

    # -----------------------------------------------------------------------
    # Apply source configuration to destination via PUT
    # -----------------------------------------------------------------------
    updated: int = 0
    skipped: int = 0
    failed:  int = 0

    for src_intf in hydrated_src:
        intf_name = src_intf.get("name", "<unknown>")

        dst_intf = dst_map.get(intf_name)
        if dst_intf is None:
            logger.warning(
                "Interface '%s' not found on destination FTD — skipping.",
                intf_name,
            )
            skipped += 1
            continue

        logger.info(
            "Updating '%s' (src id=%s → dst id=%s) ...",
            intf_name,
            src_intf.get("id"),
            dst_intf.get("id"),
        )

        payload = physical_interface_payload(src_intf, dst_intf)

        try:
            response = fmc.device.devicerecord.physicalinterface.update(
                data=payload,
                container_uuid=DST_FTD_UUID,
            )
            if response.status_code in (200, 202):
                updated += 1
                logger.info("Updated '%s' successfully.", intf_name)
            else:
                failed += 1
                logger.error(
                    "Failed to update '%s' (HTTP %d): %s",
                    intf_name,
                    response.status_code,
                    response.text[:500],
                )
        except Exception:
            failed += 1
            logger.exception("Request failed for interface '%s'.", intf_name)

    logger.info(
        "Done. Updated: %d | Skipped: %d | Failed: %d.", updated, skipped, failed
    )

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
