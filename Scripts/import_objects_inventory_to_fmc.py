#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_objects_inventory_to_fmc.py

Reads the timestamped JSON files produced by export_objects_inventory.py in
FMC/Responses/ and recreates the same objects on a destination FMC. Objects
that already exist on the destination (matched by name within their object
type) are skipped. Composite objects (Network Groups, Port Object Groups)
have their members re-linked to destination-FMC UUIDs by name; a source-FMC
UUID is never reused.

Consolidates the object inventory produced by:
    object_hosts, object_networks, object_protocolportobjects, object_ports,
    object_securityzones, object_interfacegroups, object_networkgroups,
    object_port_groups

Notes:
    - '/object/ports' (object_ports_*.json) is a read-only, polymorphic view
      that mixes Protocol Port objects with ICMPv4/ICMPv6 objects. It has no
      create endpoint of its own, so each entry is dispatched to its real
      endpoint by its own 'type' field. Protocol Port entries duplicate
      object_protocolportobjects_*.json and are simply skipped as already
      existing; ICMPv4Object/ICMPv6Object entries are the only ones actually
      created from this file.
    - Security Zone / Interface Group 'interfaces' and 'devices' are
      device-specific and not portable across FMCs, so zones/groups are
      created without them. Assign interfaces separately on the destination.
    - Network Group members of type Range/FQDN must already exist on the
      destination FMC; this script does not export/create those types.

Usage:
    Run this script directly. It will prompt for destination FMC credentials.
    Pass --timestamp/--run YYYYMMDD-HHMMSS to import one specific export run
    (all 8 files for that timestamp must exist). If omitted, the most
    recently modified file is used independently for each object type.

    python import_objects_inventory_to_fmc.py [--timestamp 20260721-143000]

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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

RESPONSES_DIR = Path(__file__).resolve().parent.parent / "FMC" / "Responses"

# object type key -> export filename stem (matches export_objects_inventory.py)
FILE_STEMS: Dict[str, str] = {
    "hosts": "object_hosts",
    "networks": "object_networks",
    "protocolportobjects": "object_protocolportobjects",
    "ports": "object_ports",
    "securityzones": "object_securityzones",
    "interfacegroups": "object_interfacegroups",
    "networkgroups": "object_networkgroups",
    "portgroups": "object_port_groups",
}

# Maps an object 'type' (as recorded in exported data) to the matching
# fireREST client attribute under fmc.object. Shared by every lookup in this
# script: existence checks for literal objects and member resolution for
# Network Groups / Port Object Groups.
OBJECT_TYPE_TO_CLIENT_ATTR: Dict[str, str] = {
    "host": "host",
    "network": "network",
    "networkgroup": "networkgroup",
    "range": "range",
    "fqdn": "fqdn",
    "protocolportobject": "protocolportobject",
    "icmpv4object": "icmpv4object",
    "icmpv6object": "icmpv6object",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for run/timestamp selection."""
    parser = argparse.ArgumentParser(
        description="Import an FMC/Responses/ object inventory export into a destination FMC."
    )
    parser.add_argument(
        "--timestamp", "--run",
        dest="timestamp",
        default=None,
        help=(
            "Export run timestamp (YYYYMMDD-HHMMSS) to import, matching the suffix "
            "used by export_objects_inventory.py. All 8 files for that timestamp must "
            "exist. If omitted, the most recently modified file is used independently "
            "for each object type."
        ),
    )
    return parser.parse_args()


def select_run_files(timestamp: Optional[str]) -> Dict[str, Path]:
    """
    Resolve the JSON export file to use for each object type.

    Args:
        timestamp (Optional[str]): If given, every type must have a file matching
            '{stem}_{timestamp}.json' (a single coherent export run). If None, the
            most recently modified '{stem}_*.json' file is selected independently
            for each type.

    Returns:
        Dict[str, Path]: Object type key -> resolved file path.

    Raises:
        SystemExit: If a required file cannot be found.
    """
    selected: Dict[str, Path] = {}
    missing: List[str] = []

    for key, stem in FILE_STEMS.items():
        if timestamp:
            candidate = RESPONSES_DIR / f"{stem}_{timestamp}.json"
            if candidate.is_file():
                selected[key] = candidate
            else:
                missing.append(str(candidate))
        else:
            matches = sorted(RESPONSES_DIR.glob(f"{stem}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                selected[key] = matches[0]
            else:
                missing.append(f"{stem}_*.json (no files found in {RESPONSES_DIR})")

    if missing:
        logger.error("Cannot proceed: missing required export file(s):")
        for m in missing:
            logger.error("  - %s", m)
        raise SystemExit(1)

    for key, path in selected.items():
        logger.info("Using %s -> %s", key, path.name)

    return selected


def load_objects_from_json(filepath: Path, label: str) -> List[Dict[str, Any]]:
    """
    Load an exported object list from a JSON file.

    Accepts either a plain JSON array or a paged FMC GET response of the
    form {"items": [...], "paging": {...}}.

    Args:
        filepath (Path): Path to the exported JSON file.
        label (str): Human-readable label for logging.

    Returns:
        List[Dict[str, Any]]: Object definitions.

    Raises:
        SystemExit: If the file is missing, unreadable, or not valid JSON.
    """
    try:
        with open(filepath, mode="r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error("JSON input file not found: '%s'.", filepath)
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON file '%s': %s", filepath, e)
        raise SystemExit(1)

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]

    if not isinstance(data, list):
        logger.error("Unexpected JSON structure in '%s': expected a list of %s.", filepath, label)
        raise SystemExit(1)

    logger.info("Loaded %d %s from '%s'.", len(data), label, filepath.name)
    return data


# ---------------------------------------------------------------------------
# Destination object cache
# ---------------------------------------------------------------------------

class ObjectCache:
    """
    Per-run cache of destination-FMC objects, keyed by fmc.object.* client
    attribute name. A full listing is fetched once per object type (instead
    of once per lookup) and kept in sync as new objects are created, so both
    existence checks and cross-object member resolution stay O(1) after the
    initial load.
    """

    def __init__(self, fmc_dst: Any):
        self.fmc = fmc_dst
        self._by_attr: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def _ensure_loaded(self, client_attr: str) -> Dict[str, Dict[str, Any]]:
        if client_attr not in self._by_attr:
            client = getattr(self.fmc.object, client_attr)
            try:
                items = client.get() or []
            except Exception:
                logger.exception("Failed to list existing '%s' objects on destination FMC.", client_attr)
                items = []
            self._by_attr[client_attr] = {item["name"]: item for item in items if item.get("name")}
        return self._by_attr[client_attr]

    def lookup(self, client_attr: str, name: str) -> Optional[Dict[str, Any]]:
        """Return the destination object with the given name, or None if not present."""
        return self._ensure_loaded(client_attr).get(name)

    def remember(self, client_attr: str, obj: Dict[str, Any]) -> None:
        """Record a freshly created object so later lookups in this run see it."""
        if obj and obj.get("name"):
            self._ensure_loaded(client_attr)[obj["name"]] = obj


# ---------------------------------------------------------------------------
# Object resolution (for group members)
# ---------------------------------------------------------------------------

def resolve_object(
    cache: ObjectCache,
    obj_ref: Dict[str, Any],
    field_label: str,
    rec_desc: str,
    missing: List[Tuple[str, str]],
) -> Optional[Dict[str, str]]:
    """
    Resolve a source-FMC object reference (type/name/id) to its destination-FMC
    equivalent by looking it up by name in the cache.

    Args:
        cache (ObjectCache): Destination-FMC object cache.
        obj_ref (Dict[str, Any]): Object reference from the exported record.
        field_label (str): Name of the field this reference came from (for logging).
        rec_desc (str): Human-readable record identifier (for logging).
        missing (List[Tuple[str, str]]): Accumulator for (type, name) pairs that could not be resolved.

    Returns:
        Optional[Dict[str, str]]: {"type", "id", "name"} for the destination object, or None on failure.
    """
    obj_type = obj_ref.get("type")
    obj_name = obj_ref.get("name")

    if not obj_type or not obj_name:
        logger.error("[%s] Field '%s' is missing 'type' or 'name' in source data: %s", rec_desc, field_label, obj_ref)
        missing.append((obj_type or "Unknown", obj_name or "Unknown"))
        return None

    client_attr = OBJECT_TYPE_TO_CLIENT_ATTR.get(obj_type.lower())
    if client_attr is None:
        logger.error(
            "[%s] Field '%s' references unsupported object type '%s' (object '%s').",
            rec_desc, field_label, obj_type, obj_name,
        )
        missing.append((obj_type, obj_name))
        return None

    found = cache.lookup(client_attr, obj_name)
    if not found:
        logger.error(
            "[%s] Missing referenced object: %s '%s' (field '%s') not found on destination FMC.",
            rec_desc, obj_type, obj_name, field_label,
        )
        missing.append((obj_type, obj_name))
        return None

    return {"type": found.get("type", obj_type), "id": found["id"], "name": found.get("name", obj_name)}


def resolve_members(
    cache: ObjectCache,
    members: List[Dict[str, Any]],
    rec_desc: str,
    missing: List[Tuple[str, str]],
) -> Optional[List[Dict[str, str]]]:
    """Resolve every member reference in a group's 'objects' list. Returns None if any member fails."""
    resolved: List[Dict[str, str]] = []
    ok = True
    for member in members:
        result = resolve_object(cache, member, "objects[]", rec_desc, missing)
        if result is None:
            ok = False
        else:
            resolved.append(result)
    return resolved if ok else None


# ---------------------------------------------------------------------------
# Creation helper (shared by every object type)
# ---------------------------------------------------------------------------

def get_or_create(cache: ObjectCache, client_attr: str, payload: Dict[str, Any], rec_desc: str) -> str:
    """
    Create an object on the destination FMC if one with the same name does
    not already exist for that object type.

    Returns:
        str: 'skipped' (already existed), 'created', or 'failed'.
    """
    name = payload.get("name")
    existing = cache.lookup(client_attr, name)
    if existing:
        logger.info("[%s] Already exists on destination FMC (id=%s). Skipping creation.", rec_desc, existing.get("id"))
        return "skipped"

    client = getattr(cache.fmc.object, client_attr)
    try:
        response = client.create(data=payload)
    except Exception:
        logger.exception("[%s] Error creating object on destination FMC.", rec_desc)
        return "failed"

    status = getattr(response, "status_code", None)
    if status != 201:
        text = getattr(response, "text", "")
        logger.error("[%s] Failed to create (HTTP %s): %s", rec_desc, status, text[:500])
        return "failed"

    logger.info("[%s] Created successfully.", rec_desc)
    try:
        created = response.json()
    except Exception:
        created = {"name": name}
    cache.remember(client_attr, created)
    return "created"


# ---------------------------------------------------------------------------
# Payload builders — literal objects (no member resolution required)
# ---------------------------------------------------------------------------

def _copy_optional(rec: Dict[str, Any], payload: Dict[str, Any], *fields: str) -> None:
    for field_name in fields:
        value = rec.get(field_name)
        if value not in (None, ""):
            payload[field_name] = value


def payload_host(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name, value = rec.get("name"), rec.get("value")
    if not name or not value:
        return None
    payload: Dict[str, Any] = {"type": "Host", "name": name, "value": value}
    _copy_optional(rec, payload, "description", "overridable")
    return payload


def payload_network(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name, value = rec.get("name"), rec.get("value")
    if not name or not value:
        return None
    payload: Dict[str, Any] = {"type": "Network", "name": name, "value": value}
    _copy_optional(rec, payload, "description", "overridable")
    return payload


def payload_protocolportobject(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = rec.get("name")
    if not name:
        return None
    payload: Dict[str, Any] = {"type": "ProtocolPortObject", "name": name}
    _copy_optional(rec, payload, "protocol", "port", "description", "overridable")
    return payload


def payload_icmpv4object(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = rec.get("name")
    if not name:
        return None
    payload: Dict[str, Any] = {"type": "ICMPV4Object", "name": name}
    if rec.get("icmpType") not in (None, ""):
        payload["icmpType"] = rec["icmpType"]
    if rec.get("code") is not None:
        payload["code"] = rec["code"]
    _copy_optional(rec, payload, "description", "overridable")
    return payload


def payload_icmpv6object(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = rec.get("name")
    if not name:
        return None
    payload: Dict[str, Any] = {"type": "ICMPV6Object", "name": name}
    if rec.get("icmpType") not in (None, ""):
        payload["icmpType"] = rec["icmpType"]
    if rec.get("code") is not None:
        payload["code"] = rec["code"]
    _copy_optional(rec, payload, "description", "overridable")
    return payload


def payload_securityzone(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name, interface_mode = rec.get("name"), rec.get("interfaceMode")
    if not name or not interface_mode:
        return None
    if rec.get("interfaces") or rec.get("devices"):
        logger.info(
            "Security Zone '%s': device/interface assignments are not portable across FMCs "
            "and will not be migrated; zone will be created without interfaces.",
            name,
        )
    payload: Dict[str, Any] = {"type": "SecurityZone", "name": name, "interfaceMode": interface_mode}
    _copy_optional(rec, payload, "description")
    return payload


def payload_interfacegroup(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name, interface_mode = rec.get("name"), rec.get("interfaceMode")
    if not name or not interface_mode:
        return None
    if rec.get("interfaces") or rec.get("devices"):
        logger.info(
            "Interface Group '%s': device/interface assignments are not portable across FMCs "
            "and will not be migrated; group will be created without interfaces.",
            name,
        )
    payload: Dict[str, Any] = {"type": "InterfaceGroup", "name": name, "interfaceMode": interface_mode}
    _copy_optional(rec, payload, "description")
    return payload


# Dispatch table for object_ports_*.json: '/object/ports' is a read-only,
# polymorphic aggregate of Protocol Port + ICMP objects, so each entry must
# be routed to its real endpoint by its own 'type' field.
PORTS_DISPATCH: Dict[str, Tuple[str, Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]]] = {
    "protocolportobject": ("protocolportobject", payload_protocolportobject),
    "icmpv4object": ("icmpv4object", payload_icmpv4object),
    "icmpv6object": ("icmpv6object", payload_icmpv6object),
}


# ---------------------------------------------------------------------------
# Payload builders — composite objects (require member resolution)
# ---------------------------------------------------------------------------

def build_networkgroup_payload(
    cache: ObjectCache, rec: Dict[str, Any], rec_desc: str, missing: List[Tuple[str, str]]
) -> Optional[Dict[str, Any]]:
    payload: Dict[str, Any] = {"type": "NetworkGroup", "name": rec["name"]}
    _copy_optional(rec, payload, "description")

    literals = rec.get("literals") or []
    if literals:
        payload["literals"] = [{"type": lit.get("type"), "value": lit.get("value")} for lit in literals]

    resolved_members = resolve_members(cache, rec.get("objects") or [], rec_desc, missing)
    if resolved_members is None:
        return None
    if resolved_members:
        payload["objects"] = resolved_members
    return payload


def build_portobjectgroup_payload(
    cache: ObjectCache, rec: Dict[str, Any], rec_desc: str, missing: List[Tuple[str, str]]
) -> Optional[Dict[str, Any]]:
    payload: Dict[str, Any] = {"type": "PortObjectGroup", "name": rec["name"]}
    _copy_optional(rec, payload, "description")

    resolved_members = resolve_members(cache, rec.get("objects") or [], rec_desc, missing)
    if resolved_members is None:
        return None
    if resolved_members:
        payload["objects"] = resolved_members
    return payload


# ---------------------------------------------------------------------------
# Stage processing
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    label: str
    total: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0
    missing: Set[Tuple[str, str]] = field(default_factory=set)


def process_literal_stage(
    cache: ObjectCache,
    records: List[Dict[str, Any]],
    client_attr: str,
    payload_builder: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    label: str,
) -> StageResult:
    """Create every record in a literal (non-composite) object type."""
    result = StageResult(label=label, total=len(records))
    for index, rec in enumerate(records, start=1):
        rec_desc = f"{label} #{index} ('{rec.get('name', '?')}')"
        payload = payload_builder(rec)
        if payload is None:
            logger.error("[%s] Could not build payload from source record (missing required fields).", rec_desc)
            result.failed += 1
            continue

        status = get_or_create(cache, client_attr, payload, rec_desc)
        if status == "skipped":
            result.skipped += 1
        elif status == "created":
            result.created += 1
        else:
            result.failed += 1
    return result


def process_ports_stage(cache: ObjectCache, records: List[Dict[str, Any]], label: str) -> StageResult:
    """Dispatch every /object/ports entry to its real endpoint by its own 'type' field."""
    result = StageResult(label=label, total=len(records))
    for index, rec in enumerate(records, start=1):
        rec_type = (rec.get("type") or "").lower()
        rec_desc = f"{label} #{index} ('{rec.get('name', '?')}', type={rec.get('type')})"

        dispatch = PORTS_DISPATCH.get(rec_type)
        if dispatch is None:
            logger.error("[%s] Unsupported/unknown port object type '%s'; skipping.", rec_desc, rec.get("type"))
            result.failed += 1
            continue

        client_attr, builder = dispatch
        payload = builder(rec)
        if payload is None:
            logger.error("[%s] Could not build payload from source record (missing required fields).", rec_desc)
            result.failed += 1
            continue

        status = get_or_create(cache, client_attr, payload, rec_desc)
        if status == "skipped":
            result.skipped += 1
        elif status == "created":
            result.created += 1
        else:
            result.failed += 1
    return result


def process_group_stage(
    cache: ObjectCache,
    records: List[Dict[str, Any]],
    client_attr: str,
    payload_builder: Callable[[ObjectCache, Dict[str, Any], str, List[Tuple[str, str]]], Optional[Dict[str, Any]]],
    label: str,
) -> StageResult:
    """
    Create composite (group) objects that may reference each other (e.g. a
    Network Group nested inside another Network Group). Export order does
    not guarantee dependency order, so unresolved records are retried in
    subsequent passes until no further progress is made.
    """
    result = StageResult(label=label, total=len(records))
    pending: List[Tuple[int, Dict[str, Any]]] = []

    for index, rec in enumerate(records, start=1):
        if not rec.get("name"):
            logger.error("%s #%d: missing required field 'name'; skipping.", label, index)
            result.failed += 1
            continue
        pending.append((index, rec))

    last_missing: Dict[int, List[Tuple[str, str]]] = {}
    max_passes = len(pending) + 1

    for _ in range(max_passes):
        if not pending:
            break

        still_pending: List[Tuple[int, Dict[str, Any]]] = []
        progress = False

        for index, rec in pending:
            rec_desc = f"{label} #{index} ('{rec['name']}')"
            rec_missing: List[Tuple[str, str]] = []
            payload = payload_builder(cache, rec, rec_desc, rec_missing)

            if payload is None:
                last_missing[index] = rec_missing
                still_pending.append((index, rec))
                continue

            last_missing.pop(index, None)
            progress = True
            status = get_or_create(cache, client_attr, payload, rec_desc)
            if status == "skipped":
                result.skipped += 1
            elif status == "created":
                result.created += 1
            else:
                result.failed += 1

        pending = still_pending
        if not progress:
            break

    for index, rec in pending:
        rec_desc = f"{label} #{index} ('{rec['name']}')"
        result.missing.update(last_missing.get(index, []))
        logger.error("[%s] Skipped: one or more referenced members could not be resolved.", rec_desc)
        result.failed += 1

    return result


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: List[StageResult]) -> None:
    logger.info("=" * 78)
    logger.info("Import Summary")
    logger.info("  %-24s %8s %8s %8s %8s", "Object Type", "Total", "Created", "Skipped", "Failed")

    totals = {"total": 0, "created": 0, "skipped": 0, "failed": 0}
    all_missing: Set[Tuple[str, str]] = set()

    for r in results:
        logger.info("  %-24s %8d %8d %8d %8d", r.label, r.total, r.created, r.skipped, r.failed)
        totals["total"] += r.total
        totals["created"] += r.created
        totals["skipped"] += r.skipped
        totals["failed"] += r.failed
        all_missing.update(r.missing)

    logger.info("  %-24s %8d %8d %8d %8d", "TOTAL", totals["total"], totals["created"], totals["skipped"], totals["failed"])

    if all_missing:
        logger.info("  Missing referenced objects/members: %d", len(all_missing))
        for obj_type, obj_name in sorted(all_missing):
            logger.info("    - %s '%s'", obj_type, obj_name)
    else:
        logger.info("  Missing referenced objects/members: none")
    logger.info("=" * 78)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    1. Resolve which export run's files to import (explicit timestamp or
       most-recent-per-type).
    2. Connect to the destination FMC.
    3. Create literal objects first (Hosts, Networks, Protocol Port Objects,
       Ports-dispatch, Security Zones, Interface Groups), then composite
       objects that reference them (Network Groups, Port Object Groups).
    4. Print a per-type and overall migration summary.
    """
    args = parse_args()
    files = select_run_files(args.timestamp)

    logger.info("Enter credentials for the destination FMC.")
    credentials = utils.prompt_fmc_credentials()
    fmc_dst = utils.fmc_connect(*credentials)
    cache = ObjectCache(fmc_dst)

    hosts = load_objects_from_json(files["hosts"], "Hosts")
    networks = load_objects_from_json(files["networks"], "Networks")
    protocolportobjects = load_objects_from_json(files["protocolportobjects"], "Protocol Port Objects")
    ports = load_objects_from_json(files["ports"], "Ports")
    securityzones = load_objects_from_json(files["securityzones"], "Security Zones")
    interfacegroups = load_objects_from_json(files["interfacegroups"], "Interface Groups")
    networkgroups = load_objects_from_json(files["networkgroups"], "Network Groups")
    portgroups = load_objects_from_json(files["portgroups"], "Port Object Groups")

    results: List[StageResult] = [
        process_literal_stage(cache, hosts, "host", payload_host, "Hosts"),
        process_literal_stage(cache, networks, "network", payload_network, "Networks"),
        process_literal_stage(
            cache, protocolportobjects, "protocolportobject", payload_protocolportobject, "Protocol Port Objects"
        ),
        process_ports_stage(cache, ports, "Ports (ICMP dispatch)"),
        process_literal_stage(cache, securityzones, "securityzone", payload_securityzone, "Security Zones"),
        process_literal_stage(cache, interfacegroups, "interfacegroup", payload_interfacegroup, "Interface Groups"),
        process_group_stage(cache, networkgroups, "networkgroup", build_networkgroup_payload, "Network Groups"),
        process_group_stage(cache, portgroups, "portobjectgroup", build_portobjectgroup_payload, "Port Object Groups"),
    ]

    print_summary(results)

    fmc_dst.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
