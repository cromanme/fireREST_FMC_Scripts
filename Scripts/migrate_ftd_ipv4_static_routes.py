#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_ftd_ipv4_static_routes.py

Connects to a single FMC, reads all IPv4 static routes from a source FTD,
and recreates them on a target FTD within the same FMC.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set SRC_FTD_UUID and DST_FTD_UUID to the source and target device UUIDs.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Note:
    For devices in HA/Cluster, use the UUID of the Active/Control unit.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

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

SRC_FTD_UUID: str = "0f2e6c72-405f-11ed-8def-ebb33cfc5f25"
DST_FTD_UUID: str = "cc609250-3d1b-11f0-ad79-eb463c9df8f2"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ipv4_static_route_payload(route: Dict) -> Dict:
    """
    Build a minimal creation payload from a source route dict.

    Args:
        route (Dict): Route definition as returned by the FMC API.

    Returns:
        Dict: Payload suitable for POSTing to FMC.
    """
    return {
        "interfaceName":    route["interfaceName"],
        "selectedNetworks": route["selectedNetworks"],
        "gateway":          route["gateway"],
        "metricValue":      route.get("metricValue", 1),
        "type":             "IPv4StaticRoute",
        "isTunneled":       route.get("isTunneled", False),
    }


def get_object(fmc, object_name: str, object_type: str) -> Optional[Dict]:
    """
    Retrieve an object from FMC by name and type.

    Args:
        fmc: Authenticated FMC client instance.
        object_name (str): Name of the object to retrieve.
        object_type (str): Object type — 'network' or 'host'.

    Returns:
        Optional[Dict]: Dict with 'type', 'name', 'id', or None on failure.
    """
    try:
        if object_type == "network":
            response = fmc.object.network.get(name=object_name)
        elif object_type == "host":
            response = fmc.object.host.get(name=object_name)
        else:
            logger.error("Unsupported object type: %s", object_type)
            return None

        if response and isinstance(response, dict) and "error" not in response:
            logger.info("Retrieved %s object: '%s'.", object_type, object_name)
            return {
                "type": response.get("type"),
                "name": response.get("name"),
                "id":   response.get("id"),
            }

        logger.error(
            "Error retrieving %s object '%s': %s",
            object_type, object_name, response,
        )
    except Exception:
        logger.exception("Failed to retrieve %s object '%s'.", object_type, object_name)

    return None


def get_network_object(fmc, object_name: str) -> Optional[Dict]:
    """Retrieve a Network object from FMC by name."""
    return get_object(fmc, object_name, "network")


def get_host_object(fmc, object_name: str) -> Optional[Dict]:
    """Retrieve a Host object from FMC by name."""
    return get_object(fmc, object_name, "host")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Read IPv4 static routes from the source FTD and create them on the target FTD.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    logger.info("Retrieving IPv4 Static Routes from source FTD: %s", SRC_FTD_UUID)
    try:
        routes = fmc.device.devicerecord.routing.ipv4staticroute.get(
            container_uuid=SRC_FTD_UUID
        )
    except Exception:
        logger.exception("Failed to retrieve IPv4 Static Routes.")
        raise SystemExit(1)

    if not routes:
        logger.warning("No IPv4 Static Routes found on source FTD %s.", SRC_FTD_UUID)
        fmc.conn.session.close()
        return

    created: int = 0
    failed:  int = 0

    for route in routes:
        payload = ipv4_static_route_payload(route)
        logger.info("Creating route: %s", payload)
        try:
            fmc.device.devicerecord.routing.ipv4staticroute.create(
                data=payload,
                container_uuid=DST_FTD_UUID,
            )
            logger.info("Created IPv4 static route successfully.")
            created += 1
        except Exception:
            logger.exception("Failed to create route: %s", payload)
            failed += 1

    logger.info("Done. Created: %d | Failed: %d.", created, failed)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
