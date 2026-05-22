#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_securityzone_byid.py

Connects to a Cisco FMC and retrieves a specific Security Zone object by
UUID, saving the result to a JSON file.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set SECURITY_ZONE_UUID to the UUID of the Security Zone to retrieve.

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

OUTPUT_FILE: str          = "securityzone_byid.json"
SECURITY_ZONE_UUID: str   = "5c263666-4bf6-11ed-a421-90d5b5de92a2"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve a specific Security Zone by UUID from FMC and save to JSON."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        response = fmc.object.securityzone.get(uuid=SECURITY_ZONE_UUID)
    except Exception:
        logger.exception(
            "Failed to retrieve Security Zone '%s' from FMC.", SECURITY_ZONE_UUID
        )
        raise SystemExit(1)

    if not response:
        logger.warning("Security Zone '%s' not found in FMC.", SECURITY_ZONE_UUID)
        raise SystemExit(0)

    utils.save_json_to_file(filename=OUTPUT_FILE, data=response)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
