#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_ftd_ipv4_static_routes_using_two_fmc_v0.2.py

Replicates IPv4 static routes from a source FTD (managed by FMC-01) to a
target FTD (managed by FMC-02). Missing Host and Network objects on FMC-02
are automatically created from the FMC-01 definitions.

Usage:
    Run this script directly. It will prompt for FMC-01 and FMC-02 credentials
    separately. Set SRC_FTD_UUID and DST_FTD_UUID to the correct device UUIDs.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

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

SRC_FTD_UUID: str = "4426897c-3026-11ec-8852-c419e6a97a79"
DST_FTD_UUID: str = "df65f2a2-73ce-11f0-a4e9-ee4f0499890f"


# ---------- Payload & response helpers ----------

def ipv4_static_route_payload(src_route: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a normalized IPv4 static route payload from a source route dict.

    Required keys in src_route: 'interfaceName', 'selectedNetworks', 'gateway'.
    Optional keys: 'metricValue', 'isTunneled'.

    Returns:
        Minimal payload ready for create() after object references are mapped to target FMC IDs.
    """
    required = ("interfaceName", "selectedNetworks", "gateway")
    missing = [k for k in required if k not in src_route]
    if missing:
        raise KeyError(f"Missing required route fields: {', '.join(missing)}")

    return {
        "interfaceName": src_route["interfaceName"],
        "selectedNetworks": list(src_route["selectedNetworks"]),
        "gateway": dict(src_route["gateway"]),
        "metricValue": src_route.get("metricValue", 1),
        "type": "IPv4StaticRoute",
        "isTunneled": src_route.get("isTunneled", False),
    }


def extract_routes(raw: Any) -> List[Dict[str, Any]]:
    """
    Normalize FMC GET response with routes into a list.
    Supports:
        - list of dicts
        - dict with 'items' (FMC paging format)
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw["items"]
    logger.warning("Unexpected routes response shape: %s", type(raw).__name__)
    return []


# ---------- Object lookup/replication helpers ----------

def _object_client_for_type(fmc: Any, obj_type: str) -> Optional[Any]:
    """
    Return the FMC object client for a given object type.
    Supports basic types commonly referenced in routes: 'Host', 'Network'.
    """
    obj_type = (obj_type or "").lower()
    try:
        if obj_type == "host":
            return fmc.object.host
        if obj_type == "network":
            return fmc.object.network
    except Exception:
        pass
    return None


def get_object_on_fmc(fmc: Any, obj_ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Try to fetch an object on the given FMC by ID (preferred) or by name.
    """
    obj_type = obj_ref.get("type")
    name = obj_ref.get("name")
    oid = obj_ref.get("id")

    client = _object_client_for_type(fmc, obj_type)
    if client is None:
        logger.error("Unsupported object type on lookup: %s", obj_type)
        return None

    # Try by ID first (if SDK supports it), then by name
    try:
        if oid:
            resp = client.get(id=oid)
            if resp:
                return resp if isinstance(resp, dict) else getattr(resp, "json", lambda: None)()
    except Exception:
        # Not fatal; fall back to name
        logger.debug("Lookup by id failed for %s(%s); trying by name.", obj_type, oid)

    if name:
        try:
            resp = client.get(name=name)
            if resp:
                return resp if isinstance(resp, dict) else getattr(resp, "json", lambda: None)()
        except Exception:
            logger.debug("Lookup by name failed for %s('%s').", obj_type, name)

    return None


def fetch_full_object_from_source(src_fmc: Any, obj_ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Retrieve the full object definition from the source FMC using id or name.
    """
    obj_type = obj_ref.get("type")
    client = _object_client_for_type(src_fmc, obj_type)
    if client is None:
        logger.error("Unsupported object type on source: %s", obj_type)
        return None

    # Prefer ID (unique); fallback to name
    try:
        if obj_ref.get("id"):
            resp = client.get(id=obj_ref["id"])
            if resp:
                return resp if isinstance(resp, dict) else getattr(resp, "json", lambda: None)()
    except Exception:
        logger.debug("Source get by id failed for %s(%s).", obj_type, obj_ref.get("id"))

    try:
        if obj_ref.get("name"):
            resp = client.get(name=obj_ref["name"])
            if resp:
                return resp if isinstance(resp, dict) else getattr(resp, "json", lambda: None)()
    except Exception:
        logger.debug("Source get by name failed for %s('%s').", obj_type, obj_ref.get("name"))

    return None


def create_object_on_target(dst_fmc: Any, src_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Create an object on the target FMC using the definition from source FMC.
    Removes fields not accepted on create (id/links/metadata/overridable).
    """
    obj_type = src_obj.get("type")
    client = _object_client_for_type(dst_fmc, obj_type)
    if client is None:
        logger.error("Unsupported object type on target: %s", obj_type)
        return None

    create_payload = dict(src_obj)  # shallow copy
    for k in ("id", "links", "metadata", "overridable"):
        create_payload.pop(k, None)

    try:
        resp = client.create(data=create_payload)
    except Exception:
        logger.exception("Failed to create %s '%s' on target FMC.", obj_type, src_obj.get("name"))
        return None

    # Normalize response to dict
    if isinstance(resp, dict):
        return resp
    try:
        if hasattr(resp, "json"):
            return resp.json()
    except Exception:
        pass

    logger.warning("Created %s '%s' but could not parse response.", obj_type, src_obj.get("name"))
    return None


def ensure_object_on_target(src_fmc: Any, dst_fmc: Any, obj_ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Ensure the given object (by name/type) exists on the target FMC.
    If missing, pull full definition from source and create on target.

    Returns:
        Target FMC object dict (must include 'id') or None.
    """
    # Already exists on target?
    existing = get_object_on_fmc(dst_fmc, obj_ref)
    if existing and isinstance(existing, dict) and existing.get("id"):
        return existing

    # Fetch the full object from source, then create on target
    src_obj = fetch_full_object_from_source(src_fmc, obj_ref)
    if not src_obj:
        logger.error("Cannot replicate object; not found on source: %s", obj_ref)
        return None

    created = create_object_on_target(dst_fmc, src_obj)
    if created and created.get("id"):
        logger.info("Replicated %s '%s' to target FMC.", created.get("type"), created.get("name"))
        return created

    logger.error("Failed to replicate object to target: %s", obj_ref)
    return None


def remap_route_objects_to_target(src_fmc: Any, dst_fmc: Any, route_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    For a route payload, ensure all referenced objects exist on target FMC and
    replace references with the target object IDs.

    Mutates and returns a new payload dict safe to send to FMC-02.
    """
    new_payload = dict(route_payload)
    new_selected: list[Dict[str, Any]] = []

    # Handle selectedNetworks
    for ref in route_payload.get("selectedNetworks", []):
        if not isinstance(ref, dict):
            logger.error("Invalid selectedNetworks element (expected dict): %r", ref)
            return None
        tgt = ensure_object_on_target(src_fmc, dst_fmc, ref)
        if not tgt:
            logger.error("Missing required network object for route: %s", ref)
            return None
        # Build target reference (type/name/id) – ID must be the target one
        new_selected.append({"type": tgt.get("type"), "name": tgt.get("name"), "id": tgt.get("id")})

    new_payload["selectedNetworks"] = new_selected

    # Handle gateway.object
    gw_obj = route_payload.get("gateway", {}).get("object")
    if not isinstance(gw_obj, dict):
        logger.error("Invalid or missing gateway.object in route payload.")
        return None

    tgt_gw = ensure_object_on_target(src_fmc, dst_fmc, gw_obj)
    if not tgt_gw:
        logger.error("Missing required gateway object for route: %s", gw_obj)
        return None

    new_payload["gateway"] = {"object": {"type": tgt_gw.get("type"), "name": tgt_gw.get("name"), "id": tgt_gw.get("id")}}
    return new_payload


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    1. Connect to FMC-01 (source) and FMC-02 (target).
    2. Retrieve IPv4 static routes from the source FTD.
    3. Ensure all referenced Host/Network objects exist on FMC-02.
    4. Create equivalent routes on the target FTD.
    """
    src_ftd_uuid = SRC_FTD_UUID
    dst_ftd_uuid = DST_FTD_UUID

    # Connect to FMC-01 (source)
    logger.info("Enter credentials for FMC-01 (source).")
    src_credentials = utils.prompt_fmc_credentials()
    fmc_src = utils.fmc_connect(*src_credentials)

    # Connect to FMC-02 (target)
    logger.info("Enter credentials for FMC-02 (target).")
    dst_credentials = utils.prompt_fmc_credentials()
    fmc_dst = utils.fmc_connect(*dst_credentials)

    # 1) Read routes from FMC-01 (source)
    logger.info("Retrieving IPv4 Static Routes from FMC-01 / FTD: %s", src_ftd_uuid)
    try:
        raw    = fmc_src.device.devicerecord.routing.ipv4staticroute.get(container_uuid=src_ftd_uuid)
        routes = extract_routes(raw)
    except Exception:
        logger.exception("Failed to retrieve IPv4 Static Routes from FMC-01 for device %s", src_ftd_uuid)
        raise SystemExit(1)

    if not routes:
        logger.warning("No IPv4 Static Routes found on source device %s.", src_ftd_uuid)
        fmc_src.conn.session.close()
        return

    logger.info("Found %d IPv4 Static Routes on source device %s.", len(routes), src_ftd_uuid)
    created, failed = 0, 0

    # 2) Copy routes to target FTD
    logger.info("Replicating routes to FMC-02 / FTD: %s", dst_ftd_uuid)
    for route in routes:
        remapped = remap_route_objects_to_target(fmc_src, fmc_dst, ipv4_static_route_payload(route))
        if not remapped:
            logger.error("Failed to remap route objects for: %s", route)
            failed += 1
            continue
        logger.info("Remapped route payload: %s", remapped)
        # Create the route on target FTD
        try:
            response = fmc_dst.device.devicerecord.routing.ipv4staticroute.create(
                data=remapped, container_uuid=dst_ftd_uuid
            )
            # Some SDKs return a dict; others a Response-like object.
            status = getattr(response, "status_code", None)
            if status is not None and status == 201:
                logger.info("Successfully created route: %s", remapped)
                created += 1
            else:
                logger.error("Failed to create route on target: %s", remapped)
                failed += 1
        except Exception as e:
            logger.exception("Error creating route on target: %s", e)
            failed += 1
    logger.info("Route replication complete: %d created, %d failed.", created, failed)


    # Close source FMC session
    try:
        fmc_src.conn.session.close()
        logger.info("FMC-01 session closed.")
    except Exception:
        logger.exception("Error closing FMC-01 session.")

    # Close target FMC session
    try:
        fmc_dst.conn.session.close()
        logger.info("FMC-02 session closed.")
    except Exception:
        logger.exception("Error closing FMC-02 session.")

if __name__ == "__main__":
    main()