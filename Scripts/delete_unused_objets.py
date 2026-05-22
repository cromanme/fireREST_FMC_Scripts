#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
delete_unused_objets.py

Connects to a Cisco FMC and deletes all unused Network Groups, Networks,
and Hosts from the domain, in dependency-safe order.

Usage:
    Run this script directly. It will prompt for FMC credentials.

Flow:
    1. Connect to FMC.
    2. Retrieve unused Network Groups (currently disabled — see comment).
    3. Retrieve unused Networks and delete them.
    4. Retrieve unused Hosts and delete them.

Note:
    Groups reference Networks/Hosts, so groups must be removed first.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List

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
# Helpers
# ---------------------------------------------------------------------------

def delete_items(fmc_delete, items: Iterable[Dict], *, kind: str) -> int:
    """
    Delete a collection of objects using *fmc_delete* callable.

    Args:
        fmc_delete: Callable that accepts ``uuid=<str>`` and performs the delete.
        items (Iterable[Dict]): Objects to delete; each must have an 'id' key.
        kind (str): Human-readable label for log messages (e.g. "Network").

    Returns:
        int: Number of items successfully deleted.
    """
    deleted = 0
    for obj in items:
        name   = obj.get("name", "<noname>")
        obj_id = obj.get("id")
        if not obj_id:
            logger.warning("[%s] Skipping object with no id: '%s'.", kind, name)
            continue
        try:
            fmc_delete(uuid=obj_id)
            logger.info("Deleted %s: '%s' (%s).", kind, name, obj_id)
            deleted += 1
        except Exception as e:
            logger.error("Failed to delete %s '%s' (%s): %s", kind, name, obj_id, e)
    return deleted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Connect to FMC and delete all unused Network, and Host objects.
    """
    logger.info("Enter credentials for FMC.")
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    # Unused Network Groups — disabled because the filter param is not
    # recognized by the fireREST library version in use.
    # unused_netgroups = list(fmc.object.networkgroup.get(unused_only=True))
    # logger.info("Found %d unused Network Groups.", len(unused_netgroups))
    # delete_items(fmc.object.networkgroup.delete, unused_netgroups, kind="NetworkGroup")

    unused_nets: List[Dict] = list(fmc.object.network.get(unused_only=True))
    logger.info("Found %d unused Networks.", len(unused_nets))
    nets_deleted = delete_items(fmc.object.network.delete, unused_nets, kind="Network")

    unused_hosts: List[Dict] = list(fmc.object.host.get(unused_only=True))
    logger.info("Found %d unused Hosts.", len(unused_hosts))
    hosts_deleted = delete_items(fmc.object.host.delete, unused_hosts, kind="Host")

    logger.info("Done. Total objects deleted: %d.", nets_deleted + hosts_deleted)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
