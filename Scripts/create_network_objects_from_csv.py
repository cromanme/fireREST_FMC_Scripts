#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_network_objects_from_csv.py

Reads a CSV file containing network object definitions and creates the
corresponding Host or Network objects in Cisco FMC.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set CSV_FILENAME to the path of the input CSV file.

CSV Format (with header row):
    name,description,type,value
    my-host,Example host,Host,192.168.1.1
    my-net,Example network,Network,192.168.1.0/24

Supported object types:
    - Host
    - Network

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import csv
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

CSV_FILENAME: str = "import_network_objects.csv"


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def read_objects_from_csv(filename: str) -> List[Dict[str, str]]:
    """
    Read the network object CSV and return a list of row dicts.

    Field names are lower-cased for consistent access.

    Args:
        filename (str): Path to the CSV file.

    Returns:
        List[Dict[str, str]]: Parsed rows.

    Raises:
        SystemExit: If the file is not found or cannot be read.
    """
    try:
        with open(filename, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [field.lower() for field in reader.fieldnames]
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

def create_network_object(fmc, name: str, description: str, obj_type: str, value: str) -> Optional[dict]:
    """
    Create a Host or Network object in FMC.

    Args:
        fmc: Authenticated FMC client instance.
        name (str): Object name.
        description (str): Object description.
        obj_type (str): Object type — 'Host' or 'Network'.
        value (str): IP address (Host) or CIDR (Network).

    Returns:
        Optional[dict]: Created object response, or None on failure.
    """
    payload = {
        "type": obj_type,
        "name": name,
        "value": value,
        "description": description,
    }

    try:
        if obj_type == "Network":
            response = fmc.object.network.create(payload)
        elif obj_type == "Host":
            response = fmc.object.host.create(payload)
        else:
            logger.error("Unsupported object type '%s' for object '%s'.", obj_type, name)
            return None

        if response.status_code == 201:
            logger.info("Created %s object: '%s'.", obj_type, name)
            return response
        else:
            logger.error("Failed to create object '%s': %s", name, response)
            return None

    except Exception as e:
        logger.error("Exception creating object '%s': %s", name, e)
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Read network objects from a CSV file and create them in FMC.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    rows = read_objects_from_csv(CSV_FILENAME)
    if not rows:
        logger.warning("No rows found in '%s'. Nothing to do.", CSV_FILENAME)
        raise SystemExit(0)

    created: int = 0
    failed:  int = 0

    for row in rows:
        name        = row.get("name", "").strip()
        description = row.get("description", "").strip()
        obj_type    = row.get("type", "").strip()
        value       = row.get("value", "").strip()

        logger.info("Creating %s object: '%s' (%s).", obj_type, name, value)
        result = create_network_object(fmc, name, description, obj_type, value)
        if result:
            created += 1
        else:
            failed += 1

    logger.info("Done. Created: %d | Failed: %d.", created, failed)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
