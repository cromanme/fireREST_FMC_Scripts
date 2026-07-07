#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_objects_securityzones_from_csv.py

Reads a CSV file (in the format produced by
export_objects_securityzones_to_csv.py) and creates the corresponding
Security Zone objects in Cisco FMC.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set CSV_FILENAME to the path of the input CSV file.

CSV Format (with header row, as produced by the export script):
    id,name,type,interfaceMode,description,interfaceCount,interfacesJSON
    <uuid>,SecurityZoneObject5,SecurityZone,INLINE,,2,"[{""type"": ""PhysicalInterface"", ""id"": ""Intf-UUID-1"", ""name"": ""eth1""}, {""type"": ""PhysicalInterface"", ""id"": ""Intf-UUID-2"", ""name"": ""eth2""}]"

Notes:
    - The 'id' and 'interfaceCount' columns are read-only metadata from the
      export and are not sent in the create payload.
    - 'interfacesJSON' is parsed back into the 'interfaces' list expected by
      the FMC API. Interface UUIDs must already exist on the target FMC.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import csv
import json
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

CSV_FILENAME: str = "import_securityzones.csv"


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def read_securityzones_from_csv(filename: str) -> List[Dict[str, str]]:
    """
    Read the security zone CSV and return a list of row dicts.

    Args:
        filename (str): Path to the CSV file.

    Returns:
        List[Dict[str, str]]: Parsed rows.

    Raises:
        SystemExit: If the file is not found or cannot be read.
    """
    try:
        with open(filename, mode="r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except FileNotFoundError:
        logger.error("CSV file not found: '%s'.", filename)
        raise SystemExit(1)
    except Exception as e:
        logger.error("Failed to read CSV file '%s': %s", filename, e)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# FMC helpers
# ---------------------------------------------------------------------------

def securityzone_payload(row: Dict[str, str]) -> Optional[Dict]:
    """
    Build a POST payload for a Security Zone object from a CSV row.

    Args:
        row (Dict[str, str]): Row as read from the CSV file.

    Returns:
        Optional[Dict]: Payload ready for POST to the FMC API, or None if
        the row is missing required fields or 'interfacesJSON' is malformed.
    """
    name           = row.get("name", "").strip()
    interface_mode = row.get("interfaceMode", "").strip()
    description    = row.get("description", "").strip()
    interfaces_raw = row.get("interfacesJSON", "").strip()

    if not name or not interface_mode:
        logger.error("Row missing required 'name' or 'interfaceMode': %s", row)
        return None

    try:
        interfaces = json.loads(interfaces_raw) if interfaces_raw else []
    except json.JSONDecodeError as e:
        logger.error("Failed to parse interfacesJSON for zone '%s': %s", name, e)
        return None

    payload: Dict = {
        "type":          row.get("type", "SecurityZone").strip() or "SecurityZone",
        "name":          name,
        "interfaceMode": interface_mode,
        "interfaces":    interfaces,
    }
    if description:
        payload["description"] = description

    return payload


def create_securityzone(fmc, payload: Dict) -> bool:
    """
    Create a single Security Zone object in FMC.

    Args:
        fmc: Authenticated FMC client instance.
        payload (Dict): Security zone definition to POST.

    Returns:
        bool: True if the zone was created successfully, False otherwise.
    """
    name = payload.get("name", "N/A")

    try:
        response = fmc.object.securityzone.create(data=payload)

        if response.status_code == 201:
            logger.info("Created Security Zone: '%s'.", name)
            return True

        logger.error("Failed to create Security Zone '%s': %s", name, response)
        return False

    except Exception as e:
        logger.error("Exception creating Security Zone '%s': %s", name, e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Read Security Zone objects from a CSV file and create them in FMC.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    rows = read_securityzones_from_csv(CSV_FILENAME)
    if not rows:
        logger.warning("No rows found in '%s'. Nothing to do.", CSV_FILENAME)
        raise SystemExit(0)

    created: int = 0
    failed:  int = 0

    for row in rows:
        payload = securityzone_payload(row)
        if not payload:
            failed += 1
            continue

        logger.info("Creating Security Zone: '%s'.", payload["name"])
        if create_securityzone(fmc, payload):
            created += 1
        else:
            failed += 1

    logger.info("Done. Created: %d | Failed: %d.", created, failed)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
