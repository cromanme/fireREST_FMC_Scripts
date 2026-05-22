#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
post_objects.py

Connects to a Cisco FMC and creates a sample network object (Host type).

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Update the NETWORK_OBJECT constant to define the object to create.

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

NETWORK_OBJECT: Dict = {
    "name":        "NetObject_2",
    "value":       "192.168.0.2",
    "overridable": False,
    "description": "Sample Network Object 2",
    "type":        "Host",
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Create a network object in FMC."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    logger.info("Creating network object '%s'.", NETWORK_OBJECT["name"])
    try:
        response = fmc.object.network.create(data=NETWORK_OBJECT)
        logger.info("Network object '%s' created successfully.", NETWORK_OBJECT["name"])
    except Exception:
        logger.exception("Failed to create network object '%s'.", NETWORK_OBJECT["name"])
        raise SystemExit(1)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
