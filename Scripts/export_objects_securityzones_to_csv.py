#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_objects_securityzones_to_csv.py

Connects to a Cisco FMC and exports all Security Zone objects to a
timestamped CSV file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    The CSV file is written to OUTPUT_DIR.

Outputs (created in OUTPUT_DIR):
    - fmc_securityzones_YYYYMMDD-HHMMSS.csv
      -> id,name,type,interfaceMode,description,interfaceCount,interfacesJSON

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
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

OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent / "output"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def export_securityzones(fmc, ts: str) -> str:
    """
    Export all Security Zone objects to a CSV file.

    Interfaces are serialized as a JSON string in the 'interfacesJSON'
    column, mirroring how Network Group members are exported.

    Args:
        fmc: Authenticated FMC client instance.
        ts (str): Timestamp string used in the output filename.

    Returns:
        str: Path to the written CSV file.
    """
    try:
        zones: List = fmc.object.securityzone.get()
    except Exception as e:
        logger.error("Failed to retrieve Security Zone objects: %s", e)
        return ""

    rows: List[Dict] = []
    for z in zones:
        interfaces = [
            {
                "type": intf.get("type"),
                "id":   intf.get("id"),
                "name": intf.get("name"),
            }
            for intf in (z.get("interfaces") or [])
        ]

        rows.append({
            "id":             z.get("id", ""),
            "name":           z.get("name", ""),
            "type":           z.get("type", "SecurityZone"),
            "interfaceMode":  z.get("interfaceMode", ""),
            "description":    z.get("description", ""),
            "interfaceCount": len(interfaces),
            "interfacesJSON": json.dumps(interfaces, ensure_ascii=False),
        })

    path = OUTPUT_DIR / f"fmc_securityzones_{ts}.csv"
    utils.write_csv(
        str(path),
        rows,
        ["id", "name", "type", "interfaceMode", "description", "interfaceCount", "interfacesJSON"],
    )
    logger.info("Security Zones exported: %d -> %s", len(rows), path)
    return str(path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Connect to FMC and export all Security Zone objects to a CSV file.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    logger.info("Enter credentials for FMC.")
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    export_securityzones(fmc, ts)

    logger.info("CSV generated.")

    fmc.conn.session.close()
    logger.info("FMC session closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
