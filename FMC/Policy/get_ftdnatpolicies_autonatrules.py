#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_ftdnatpolicies_natrules.py

Connects to a Cisco FMC and retrieves list of all FTD Manual NAT rules,
saving the result to a JSON file.

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

OUTPUT_FILE: str = "../Responses/ftdnatpolicies_autonatrule.json"
NAT_POLICY_UUID: str    = "005056A4-7A08-0ed3-0000-021474840082"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve all FTD Site to Site VPN topologies from FMC and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.policy.ftdnatpolicy.autonatrule.get(NAT_POLICY_UUID)
    except Exception:
        logger.exception("Failed to retrieve FTD Auto NAT Rules from FMC.")
        raise SystemExit(1)

    if not response:
        logger.warning("No FTD Auto NAT Rules found in FMC.")
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
