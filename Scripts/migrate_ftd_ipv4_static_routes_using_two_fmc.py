#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_ftd_ipv4_static_routes_using_two_fmc.py

Replicates IPv4 static routes from a source FTD (managed by FMC-01) to a
target FTD (managed by FMC-02), including automatic replication of referenced
network objects and NetworkGroups (and their members).

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
from typing import Any, Dict, List, Optional, Set, Tuple

import utils

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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
    """Normalize FMC GET response with routes into a list."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw["items"]
    logger.warning("Unexpected routes response shape: %s", type(raw).__name__)
    return []


# ---------- Object clients & lookups ----------

def _object_client_for_type(fmc: Any, obj_type: str) -> Optional[Any]:
    """
    Return the FMC object client for a given object type.
    Supports: Host, Network, NetworkGroup (case-insensitive).
    """
    t = (obj_type or "").lower()
    try:
        if t == "host":
            return fmc.object.host
        if t == "network":
            return fmc.object.network
        if t == "networkgroup":
            return fmc.object.networkgroup
    except Exception:
        pass
    return None


def get_object_on_fmc(fmc: Any, obj_ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Try to fetch an object on the given FMC by ID (preferred) or by name."""
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
    """Retrieve the full object definition from the source FMC using id or name."""
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


# ---------- Creation helpers (Host/Network/NetworkGroup) ----------

def _strip_create_unusable_fields(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Remove non-creatable fields commonly present on GET responses."""
    payload = dict(obj)
    for k in ("id", "links", "metadata", "overridable"):
        payload.pop(k, None)
    return payload


def create_object_on_target(dst_fmc: Any, src_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Create a Host/Network on the target FMC using the definition from source FMC.
    (Not for NetworkGroup — use create_network_group_on_target.)
    """
    obj_type = (src_obj.get("type") or "").lower()
    if obj_type in ("networkgroup",):
        logger.error("create_object_on_target called for NetworkGroup; use create_network_group_on_target.")
        return None

    client = _object_client_for_type(dst_fmc, src_obj.get("type"))
    if client is None:
        logger.error("Unsupported object type on target: %s", src_obj.get("type"))
        return None

    create_payload = _strip_create_unusable_fields(src_obj)

    try:
        resp = client.create(data=create_payload)
    except Exception:
        logger.exception("Failed to create %s '%s' on target FMC.", src_obj.get("type"), src_obj.get("name"))
        return None

    if isinstance(resp, dict):
        return resp
    try:
        if hasattr(resp, "json"):
            return resp.json()
    except Exception:
        pass

    logger.warning("Created %s '%s' but could not parse response.", src_obj.get("type"), src_obj.get("name"))
    return None


def create_network_group_on_target(dst_fmc: Any, src_group: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Create a NetworkGroup on target FMC. Assumes its members already exist on target FMC.
    """
    client = _object_client_for_type(dst_fmc, "NetworkGroup")
    if client is None:
        logger.error("Target FMC does not support NetworkGroup operations.")
        return None

    payload = _strip_create_unusable_fields(src_group)

    # Ensure payload.members references existing target objects by id/name/type.
    # Some SDKs expect 'members' list with objects like {'type','name','id'}.
    members = payload.get("members")
    if not isinstance(members, list) or not members:
        logger.error("NetworkGroup payload missing valid 'members'.")
        return None

    try:
        resp = client.create(data=payload)
    except Exception:
        logger.exception("Failed to create NetworkGroup '%s' on target FMC.", payload.get("name"))
        return None

    if isinstance(resp, dict):
        return resp
    try:
        if hasattr(resp, "json"):
            return resp.json()
    except Exception:
        pass

    logger.warning("Created NetworkGroup '%s' but could not parse response.", payload.get("name"))
    return None


# ---------- Ensure-on-target (recursive with cycle protection) ----------

def ensure_object_on_target(
    src_fmc: Any,
    dst_fmc: Any,
    obj_ref: Dict[str, Any],
    *,
    _visited: Optional[Set[Tuple[str, str]]] = None
) -> Optional[Dict[str, Any]]:
    """
    Ensure the given object (Host/Network/NetworkGroup) exists on the target FMC.
    - If Host/Network: create directly if missing.
    - If NetworkGroup: ensure all members first (recursively), then create the group.

    Returns:
        Target FMC object dict (must include 'id') or None.
    """
    if _visited is None:
        _visited = set()

    key = (obj_ref.get("type", ""), obj_ref.get("name", "") or obj_ref.get("id", ""))
    if key in _visited:
        # Cycle protection for nested groups
        logger.debug("Already visited %s; skipping to prevent cycles.", key)
        return get_object_on_fmc(dst_fmc, obj_ref)
    _visited.add(key)

    # If already exists on target, return it
    existing = get_object_on_fmc(dst_fmc, obj_ref)
    if existing and existing.get("id"):
        return existing

    obj_type = (obj_ref.get("type") or "").lower()

    # Fetch full definition from source
    src_obj = fetch_full_object_from_source(src_fmc, obj_ref)
    if not src_obj:
        logger.error("Cannot replicate object; not found on source: %s", obj_ref)
        return None

    if obj_type in ("host", "network"):
        created = create_object_on_target(dst_fmc, src_obj)
        if created and created.get("id"):
            logger.info("Replicated %s '%s' to target FMC.", created.get("type"), created.get("name"))
            return created
        logger.error("Failed to replicate %s to target: %s", src_obj.get("type"), obj_ref)
        return None

    if obj_type == "networkgroup":
        # Ensure each member exists on target
        members = src_obj.get("members") or []
        if not isinstance(members, list):
            logger.error("NetworkGroup '%s' has invalid 'members' field.", src_obj.get("name"))
            return None

        target_members: List[Dict[str, Any]] = []
        for m in members:
            if not isinstance(m, dict):
                logger.error("Invalid member entry in NetworkGroup '%s': %r", src_obj.get("name"), m)
                return None
            tgt_member = ensure_object_on_target(src_fmc, dst_fmc, m, _visited=_visited)
            if not tgt_member:
                logger.error("Failed to ensure member '%s' for NetworkGroup '%s'.", m.get("name"), src_obj.get("name"))
                return None
            target_members.append({"type": tgt_member.get("type"), "name": tgt_member.get("name"), "id": tgt_member.get("id")})

        # Prepare group payload for target creation
        group_payload = _strip_create_unusable_fields(src_obj)
        group_payload["members"] = target_members

        created = create_network_group_on_target(dst_fmc, group_payload)
        if created and created.get("id"):
            logger.info("Replicated NetworkGroup '%s' to target FMC.", created.get("name"))
            return created

        logger.error("Failed to replicate NetworkGroup to target: %s", obj_ref)
        return None

    logger.error("Unsupported object type during ensure: %s", obj_ref.get("type"))
    return None


# ---------- Route remapping ----------

def remap_route_objects_to_target(src_fmc: Any, dst_fmc: Any, route_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    For a route payload, ensure all referenced objects exist on target FMC and
    replace references with the target object IDs (supports Host, Network, NetworkGroup).
    """
    new_payload = dict(route_payload)
    new_selected: List[Dict[str, Any]] = []

    # selectedNetworks can contain Host, Network, or NetworkGroup
    for ref in route_payload.get("selectedNetworks", []):
        if not isinstance(ref, dict):
            logger.error("Invalid selectedNetworks element (expected dict): %r", ref)
            return None
        tgt = ensure_object_on_target(src_fmc, dst_fmc, ref)
        if not tgt:
            logger.error("Missing required network object for route: %s", ref)
            return None
        new_selected.append({"type": tgt.get("type"), "name": tgt.get("name"), "id": tgt.get("id")})

    new_payload["selectedNetworks"] = new_selected

    # gateway.object
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
# Constants
# ---------------------------------------------------------------------------

SRC_FTD_UUID: str = "0f2e6c72-405f-11ed-8def-ebb33cfc5f25"
DST_FTD_UUID: str = "cc609250-3d1b-11f0-ad79-eb463c9df8f2"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    1. Connect to FMC-01 (source) and FMC-02 (target).
    2. Retrieve IPv4 static routes from the source FTD.
    3. Ensure all referenced objects exist on FMC-02 (create if missing).
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
        raw = fmc_src.device.devicerecord.routing.ipv4staticroute.get(container_uuid=src_ftd_uuid)
        routes = extract_routes(raw)
    except Exception:
        logger.exception("Failed to retrieve IPv4 Static Routes from FMC-01 for device %s", src_ftd_uuid)
        raise SystemExit(1)

    if not routes:
        logger.warning("No IPv4 Static Routes found on source device %s.", src_ftd_uuid)
        # Close sessions and exit gracefully
        try:
            fmc_src.conn.session.close()
        finally:
            try:
                fmc_dst.conn.session.close()
            finally:
                pass
        return

    created, failed = 0, 0

    # 2) For each route, ensure objects exist on FMC-02 and create the route there
    for route in routes:
        try:
            base_payload = ipv4_static_route_payload(route)
        except KeyError as ke:
            failed += 1
            logger.error("Skipping malformed source route: %s", ke)
            continue

        mapped_payload = remap_route_objects_to_target(fmc_src, fmc_dst, base_payload)
        if not mapped_payload:
            failed += 1
            logger.error("Skipping route due to unresolved objects. Payload: %s", base_payload)
            continue

        logger.info("Creating IPv4 Static Route on FMC-02 / FTD %s with payload: %s", dst_ftd_uuid, mapped_payload)
        try:
            resp = fmc_dst.device.devicerecord.routing.ipv4staticroute.create(
                container_uuid=dst_ftd_uuid,
                data=mapped_payload,
            )

            status = getattr(resp, "status_code", None)
            if status is not None and status != 201:
                detail: Optional[Any] = None
                try:
                    if hasattr(resp, "json"):
                        detail = resp.json()
                    else:
                        detail = getattr(resp, "text", None)
                except Exception:
                    detail = None

                failed += 1
                logger.error("Create failed (status=%s) for payload: %s | detail=%s", status, mapped_payload, detail)
                continue

            if isinstance(resp, dict) and "error" in resp:
                failed += 1
                logger.error("Create failed for payload: %s | error=%s", mapped_payload, resp["error"])
                continue

            created += 1
            logger.info("Created IPv4 Static Route successfully on target.")
        except Exception:
            failed += 1
            logger.exception("Exception while creating route on target for payload: %s", mapped_payload)

    # 3) Close sessions
    try:
        fmc_src.conn.session.close()
        logger.info("FMC-01 session closed.")
    except Exception:
        logger.exception("Error closing FMC-01 session.")

    try:
        fmc_dst.conn.session.close()
        logger.info("FMC-02 session closed. Created: %d | Failed: %d", created, failed)
    except Exception:
        logger.exception("Error closing FMC-02 session.")


if __name__ == "__main__":
    main()