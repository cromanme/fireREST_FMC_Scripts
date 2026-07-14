#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_hosts.py

Connects to a Cisco FMC and retrieves all Host objects, saving the
result to a JSON file.

Usage:
    Run this script directly. It will prompt for FMC credentials.

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

OUTPUT_FILE: str = "../Responses/object_hosts.json"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve all Host objects from FMC and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.object.host.get()
    except Exception:
        logger.exception("Failed to retrieve Host objects from FMC.")
        raise SystemExit(1)

    if not response:
        logger.warning("No Host objects found in FMC.")
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
