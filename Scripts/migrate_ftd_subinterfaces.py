#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_ftd_subinterfaces.py

Connects to a single FMC, reads all sub-interfaces from a source FTD,
and recreates them on a target FTD within the same FMC using a bulk POST.

Sub-interfaces are logical constructs tied to a parent physical interface by
name (e.g. "GigabitEthernet1/4"). Because the same interface names exist on
both FTDs, no UUID remapping is required — the payload is carried over
directly after stripping GET-only fields.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set SRC_FTD_UUID and DST_FTD_UUID to the source and target device UUIDs.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Note:
    For devices in HA/Cluster, use the UUID of the Active/Control unit.
    Sub-interfaces with the same subIntfId must not already exist on the
    destination FTD. Security zone UUIDs are stable within the same FMC domain.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

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

SRC_FTD_UUID: str = "REPLACE_WITH_SOURCE_FTD_UUID"
DST_FTD_UUID: str = "REPLACE_WITH_DESTINATION_FTD_UUID"
BULK_CHUNK_SIZE: int = 1000  # max sub-interfaces per bulk POST request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fields present in a GET response that must not appear in a POST body.
_READONLY_FIELDS = frozenset({"id", "links", "metadata"})


def subinterface_payload(sub: Dict) -> Dict:
    """
    Build a POST payload from a source sub-interface dict.

    Strips GET-response-only fields (id, links, metadata) while preserving
    all configuration fields. The ``name`` field (parent physical interface
    name, e.g. "GigabitEthernet1/4") is kept as-is: it tells the FMC which
    physical interface to attach the sub-interface to, and that name is
    identical on both FTDs.

    Args:
        sub (Dict): Sub-interface as returned by the FMC GET API.

    Returns:
        Dict: Payload ready for POST to the FMC API.
    """
    return {
        key: value
        for key, value in sub.items()
        if key not in _READONLY_FIELDS
    }


def _hydrate_if_stub(fmc, device_uuid: str, sub: Dict) -> Optional[Dict]:
    """
    Return the full sub-interface detail if *sub* is a minimal stub.

    The GET-all response may return only name + id when the fireREST library
    does not append ?expanded=true. Detect this by checking for the absence
    of ``subIntfId``, which is always present in a fully expanded response.

    Args:
        fmc: Authenticated FMC client instance.
        device_uuid (str): UUID of the FTD device.
        sub (Dict): Sub-interface item from the GET-all response.

    Returns:
        Optional[Dict]: Fully populated dict, or None on failure.
    """
    if "subIntfId" in sub:
        return sub

    logger.debug(
        "Hydrating stub sub-interface '%s' (id=%s).",
        sub.get("name"), sub.get("id"),
    )
    try:
        return fmc.device.devicerecord.subinterface.get(
            container_uuid=device_uuid,
            uuid=sub["id"],
        )
    except Exception:
        logger.exception(
            "Failed to hydrate sub-interface id=%s on device %s.",
            sub.get("id"), device_uuid,
        )
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Read sub-interfaces from the source FTD and recreate them on the target
    FTD using bulk POST, chunked to BULK_CHUNK_SIZE per request.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    logger.info(
        "Retrieving sub-interfaces from source FTD: %s", SRC_FTD_UUID
    )
    try:
        raw = fmc.device.devicerecord.subinterface.get(
            container_uuid=SRC_FTD_UUID
        )
    except Exception:
        logger.exception("Failed to retrieve sub-interfaces.")
        fmc.conn.session.close()
        raise SystemExit(1)

    if not raw:
        logger.warning(
            "No sub-interfaces found on source FTD %s.", SRC_FTD_UUID
        )
        fmc.conn.session.close()
        return

    if isinstance(raw, dict):
        raw = [raw]

    # Hydrate any minimal stubs so every item has full configuration detail.
    sub_interfaces: List[Dict] = []
    for item in raw:
        full = _hydrate_if_stub(fmc, SRC_FTD_UUID, item)
        if full:
            sub_interfaces.append(full)

    logger.info(
        "Found %d sub-interface(s) on source FTD.", len(sub_interfaces)
    )

    payloads = [subinterface_payload(s) for s in sub_interfaces]

    created: int = 0
    failed:  int = 0

    for i in range(0, len(payloads), BULK_CHUNK_SIZE):
        chunk = payloads[i : i + BULK_CHUNK_SIZE]
        logger.info(
            "Bulk creating sub-interfaces %d–%d of %d ...",
            i + 1, i + len(chunk), len(payloads),
        )
        try:
            # Passing a list triggers ?bulk=true automatically in fireREST.
            response = fmc.device.devicerecord.subinterface.create(
                data=chunk,
                container_uuid=DST_FTD_UUID,
            )
            if response.status_code in (200, 201, 202):
                created += len(chunk)
                logger.info(
                    "Bulk created %d sub-interface(s) successfully.", len(chunk)
                )
            else:
                failed += len(chunk)
                logger.error(
                    "Bulk create failed (HTTP %d): %s",
                    response.status_code,
                    response.text[:500],
                )
        except Exception:
            failed += len(chunk)
            logger.exception(
                "Bulk create request failed for chunk of %d sub-interface(s).",
                len(chunk),
            )

    logger.info(
        "Done. Created: %d | Failed: %d.", created, failed
    )

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
