#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_objects_object_management.py

Connects to a Cisco FMC and exports all Host, Network, and Network Group
objects to timestamped CSV files.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    CSV files are written to OUTPUT_DIR.

Outputs (created in OUTPUT_DIR):
    - fmc_hosts_YYYYMMDD-HHMMSS.csv         -> id,name,value,type,description
    - fmc_networks_YYYYMMDD-HHMMSS.csv      -> id,name,value,type,description
    - fmc_networkgroups_YYYYMMDD-HHMMSS.csv -> id,name,memberCount,membersJSON,type,description

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
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

OUTPUT_DIR: str = "."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_group_details(fmc, group_stub: Dict) -> Dict:
    """
    Ensure a Network Group has member info.

    If the list response lacks 'objects'/'literals', fetch the full object by id.

    Args:
        fmc: Authenticated FMC client instance.
        group_stub (Dict): Partial group dict from the list endpoint.

    Returns:
        Dict: Full group definition.
    """
    if group_stub.get("objects") is not None or group_stub.get("literals") is not None:
        return group_stub
    gid = group_stub.get("id")
    if not gid:
        return group_stub
    try:
        return fmc.object.networkgroup.get(id=gid)
    except Exception:
        return group_stub


def export_hosts(fmc, ts: str) -> str:
    """
    Export all Host objects to a CSV file.

    Args:
        fmc: Authenticated FMC client instance.
        ts (str): Timestamp string used in the output filename.

    Returns:
        str: Path to the written CSV file.
    """
    try:
        hosts: List = fmc.object.host.get()
    except Exception as e:
        logger.error("Failed to retrieve Host objects: %s", e)
        return ""

    rows: List[Dict] = [
        {
            "id":          h.get("id", ""),
            "name":        h.get("name", ""),
            "value":       h.get("value", ""),
            "type":        h.get("type", "Host"),
            "description": h.get("description", ""),
        }
        for h in hosts
    ]
    path = os.path.join(OUTPUT_DIR, f"fmc_hosts_{ts}.csv")
    utils.write_csv(path, rows, ["id", "name", "value", "type", "description"])
    logger.info("Hosts exported: %d -> %s", len(rows), path)
    return path


def export_networks(fmc, ts: str) -> str:
    """
    Export all Network objects to a CSV file.

    Args:
        fmc: Authenticated FMC client instance.
        ts (str): Timestamp string used in the output filename.

    Returns:
        str: Path to the written CSV file.
    """
    try:
        networks: List = fmc.object.network.get()
    except Exception as e:
        logger.error("Failed to retrieve Network objects: %s", e)
        return ""

    rows: List[Dict] = [
        {
            "id":          n.get("id", ""),
            "name":        n.get("name", ""),
            "value":       n.get("value", ""),
            "type":        n.get("type", "Network"),
            "description": n.get("description", ""),
        }
        for n in networks
    ]
    path = os.path.join(OUTPUT_DIR, f"fmc_networks_{ts}.csv")
    utils.write_csv(path, rows, ["id", "name", "value", "type", "description"])
    logger.info("Networks exported: %d -> %s", len(rows), path)
    return path


def export_networkgroups(fmc, ts: str) -> str:
    """
    Export all Network Group objects to a CSV file.

    Members are serialized as a JSON string in the 'membersJSON' column.

    Args:
        fmc: Authenticated FMC client instance.
        ts (str): Timestamp string used in the output filename.

    Returns:
        str: Path to the written CSV file.
    """
    try:
        ngs: List = fmc.object.networkgroup.get()
    except Exception as e:
        logger.error("Failed to retrieve Network Group objects: %s", e)
        return ""

    rows: List[Dict] = []
    for g in ngs:
        g_full  = _fetch_group_details(fmc, g)
        members = []

        for obj in (g_full.get("objects") or []):
            members.append({"refType": obj.get("type"), "id": obj.get("id"), "name": obj.get("name")})

        for lit in (g_full.get("literals") or []):
            members.append({"refType": lit.get("type"), "value": lit.get("value")})

        rows.append({
            "id":           g_full.get("id", ""),
            "name":         g_full.get("name", ""),
            "memberCount":  len(members),
            "membersJSON":  json.dumps(members, ensure_ascii=False),
            "type":         g_full.get("type", "NetworkGroup"),
            "description":  g_full.get("description", ""),
        })

    path = os.path.join(OUTPUT_DIR, f"fmc_networkgroups_{ts}.csv")
    utils.write_csv(path, rows, ["id", "name", "memberCount", "membersJSON", "type", "description"])
    logger.info("Network Groups exported: %d -> %s", len(rows), path)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Connect to FMC and export Hosts, Networks, and Network Groups to CSV files.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    logger.info("Enter credentials for FMC.")
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    export_networkgroups(fmc, ts)
    export_networks(fmc, ts)
    export_hosts(fmc, ts)

    logger.info("All CSVs generated.")

    fmc.conn.session.close()
    logger.info("FMC session closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
