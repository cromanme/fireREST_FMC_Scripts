#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_networkgroups_byid.py

Connects to a Cisco FMC and retrieves a specific Network Group object by
name, saving the result to a JSON file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set NETWORK_GROUP_NAME to the name of the group to retrieve.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging

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

OUTPUT_FILE: str          = "../Responses/network_groups_byid.json"
NETWORK_GROUP_NAME: str   = "netgroups"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve a specific Network Group by name from FMC and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.object.networkgroup.get(name=NETWORK_GROUP_NAME)
    except Exception:
        logger.exception(
            "Failed to retrieve Network Group '%s' from FMC.", NETWORK_GROUP_NAME
        )
        raise SystemExit(1)

    if not response:
        logger.warning("Network Group '%s' not found in FMC.", NETWORK_GROUP_NAME)
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
