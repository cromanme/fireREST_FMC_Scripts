#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_objects_inventory.py

Connects to a Cisco FMC and exports the most common object categories to
timestamped JSON files, one file per API/category, in FMC/Responses/.

Consolidates:
    get_hosts.py, get_ports.py, get_networks.py, get_networkgroups.py,
    get_port_groups.py, get_securityzones.py, get_interfacegroups.py,
    get_protocol_port_objects.py

Usage:
    Run this script directly. It will prompt for FMC credentials.

Outputs (created in FMC/Responses/):
    object_hosts_YYYYMMDD-HHMMSS.json
    object_ports_YYYYMMDD-HHMMSS.json
    object_networks_YYYYMMDD-HHMMSS.json
    object_networkgroups_YYYYMMDD-HHMMSS.json
    object_port_groups_YYYYMMDD-HHMMSS.json
    object_securityzones_YYYYMMDD-HHMMSS.json
    object_interfacegroups_YYYYMMDD-HHMMSS.json
    object_protocolportobjects_YYYYMMDD-HHMMSS.json

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, List, NamedTuple

try:
    import utils
except ModuleNotFoundError:
    # Allow running from the Scripts/ subdirectory
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "FMC" / "Responses"


class ObjectCategory(NamedTuple):
    label: str
    filename_stem: str
    fetch: Callable[..., List[dict]]


CATEGORIES: List[ObjectCategory] = [
    ObjectCategory("Hosts", "object_hosts", lambda fmc: fmc.object.host.get()),
    ObjectCategory("Ports", "object_ports", lambda fmc: fmc.object.port.get()),
    ObjectCategory("Networks", "object_networks", lambda fmc: fmc.object.network.get()),
    ObjectCategory("Network Groups", "object_networkgroups", lambda fmc: fmc.object.networkgroup.get()),
    ObjectCategory("Port Groups", "object_port_groups", lambda fmc: fmc.object.portobjectgroup.get()),
    ObjectCategory("Security Zones", "object_securityzones", lambda fmc: fmc.object.securityzone.get()),
    ObjectCategory("Interface Groups", "object_interfacegroups", lambda fmc: fmc.object.interfacegroup.get()),
    ObjectCategory("Protocol Port Objects", "object_protocolportobjects", lambda fmc: fmc.object.protocolportobject.get()),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def export_category(fmc, category: ObjectCategory, ts: str) -> None:
    """
    Fetch one object category from FMC and save it to a dated JSON file.

    Args:
        fmc: Authenticated FMC client instance.
        category (ObjectCategory): Category to export.
        ts (str): Shared run timestamp used in the output filename.
    """
    logger.info("Retrieving %s ...", category.label)
    try:
        response = category.fetch(fmc)
    except Exception:
        logger.exception("Failed to retrieve %s from FMC.", category.label)
        return

    if not response:
        logger.warning("No %s found in FMC.", category.label)
        return

    output_file = OUTPUT_DIR / f"{category.filename_stem}_{ts}.json"
    utils.save_json_to_file(filename=str(output_file), data=response)
    logger.info("%s exported: %d object(s) -> %s", category.label, len(response), output_file)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Retrieve all common object categories from FMC and save each to a dated JSON file."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    for category in CATEGORIES:
        export_category(fmc, category, ts)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
