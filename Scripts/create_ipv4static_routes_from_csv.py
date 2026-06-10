#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_ipv4static_routes_from_csv.py

Reads a CSV file of IPv4 static route definitions and creates them on a target
FTD in bulk via the FMC REST API.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_UUID to the target device UUID and CSV_FILENAME to the input file.

CSV format (header row required):
    interfaceName, selectedNetworks (semicolon-separated), gateway

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

FTD_UUID: str = "b155923e-db11-11ee-8794-be48d41fc879"
CSV_FILENAME: str = "../Devices/devices.json"
BULK_CHUNK_SIZE: int = 1000  # max routes per bulk API request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_route_payload(interface: str, selected_nets: List[Dict], gateway_obj: Dict) -> Dict:
    """
    Build a minimal IPv4 static route creation payload.

    Args:
        interface (str): Egress interface name.
        selected_nets (List[Dict]): List of network/host object references.
        gateway_obj (Dict): Gateway host object reference.

    Returns:
        Dict: Payload suitable for POSTing to FMC.
    """
    return {
        "interfaceName":    interface,
        "selectedNetworks": selected_nets,
        "gateway":          {"object": gateway_obj},
        "metricValue":      1,
        "type":             "IPv4StaticRoute",
        "isTunneled":       False,
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
    Read IPv4 static routes from a CSV file and create them on the target FTD
    using a single bulk POST request (or multiple chunked requests for large tables).
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    csv_reader = utils.read_csv_file(CSV_FILENAME)
    if csv_reader is None:
        logger.error("Failed to read the CSV file. Exiting.")
        raise SystemExit(1)

    payloads: List[Dict] = []

    for row in csv_reader:
        interface = row["interfaceName"]
        networks  = row["selectedNetworks"]
        gateway   = row["gateway"]

        selected_nets: List[Dict] = []
        for net in networks.split(";"):
            net = net.strip()
            net_obj = get_network_object(fmc, net) or get_host_object(fmc, net)
            if net_obj:
                selected_nets.append(net_obj)
            else:
                logger.error("Network/Host object not found: '%s'. Skipping row.", net)
                break
        else:
            gateway_obj = get_host_object(fmc, gateway)
            if not gateway_obj:
                logger.error("Gateway object not found: '%s'. Skipping row.", gateway)
                continue

            payloads.append(build_route_payload(interface, selected_nets, gateway_obj))

    if not payloads:
        logger.warning("No valid route payloads built from CSV. Nothing to create.")
        fmc.conn.session.close()
        return

    logger.info("Prepared %d route payload(s) for bulk creation.", len(payloads))

    created: int = 0
    failed:  int = 0

    for i in range(0, len(payloads), BULK_CHUNK_SIZE):
        chunk = payloads[i : i + BULK_CHUNK_SIZE]
        logger.info(
            "Bulk creating routes %d–%d of %d ...",
            i + 1, i + len(chunk), len(payloads),
        )
        try:
            # Passing a list triggers ?bulk=true automatically in fireREST
            response = fmc.device.devicerecord.routing.ipv4staticroute.create(
                data=chunk,
                container_uuid=FTD_UUID,
            )
            if response.status_code in (200, 201):
                created += len(chunk)
                logger.info("Bulk created %d route(s) successfully.", len(chunk))
            else:
                failed += len(chunk)
                logger.error(
                    "Bulk create failed (HTTP %d): %s",
                    response.status_code,
                    response.text[:500],
                )
        except Exception:
            failed += len(chunk)
            logger.exception("Bulk create request failed for chunk of %d routes.", len(chunk))

    logger.info("Done. Created: %d | Failed: %d.", created, failed)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
