#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_ftd_sub_interfaces_from_json.py

Imports FTD sub-interfaces exported (as JSON) from a source FMC and recreates
them on a destination FTD managed by a different FMC.

None of the UUIDs embedded in the exported JSON are valid on the destination
FMC. Before a sub-interface is created, every embedded object reference
(Security Zone, IPv4/IPv6 Address Pool, ...) is resolved by name against the
destination FMC and rewritten with the destination UUID, and the parent
physical/EtherChannel interface is matched by name against the destination
FTD. A source-FMC UUID is never reused.

Usage:
    python import_ftd_sub_interfaces_from_json.py <input.json> [--device-uuid UUID]

    Run this script directly. It will prompt for destination FMC credentials.
    If --device-uuid is omitted, DST_FTD_UUID below is used as the target FTD.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Note:
    A raw FMC GET .../subinterfaces response only embeds "id"/"type" for
    object references such as "securityZone" -- FMC does not include a
    "name" for these references. A reference without a "name" cannot be
    resolved on the destination FMC (a source-FMC id is meaningless there)
    and is reported as a missing object; re-export with names attached if
    this occurs.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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

DST_FTD_UUID: str = "REPLACE_WITH_DESTINATION_FTD_UUID"

# Fields present in a GET response that must not appear in a POST body.
_READONLY_FIELDS = frozenset({"id", "links", "metadata"})

# Minimum fields a source record must have to be recreated as a sub-interface.
# "name" is the parent (physical/EtherChannel) interface name.
REQUIRED_FIELDS: Tuple[str, ...] = ("name", "vlanId", "subIntfId")

# Object reference 'type' (as embedded by FMC in the export) -> fmc.object.<attr>.
# Only object types with a create/read client available in fireREST are listed;
# anything else is reported as an unsupported/missing reference.
REFERENCE_TYPE_TO_CLIENT_ATTR: Dict[str, str] = {
    "securityzone": "securityzone",
    "ipv4addresspool": "ipv4addresspool",
    "ipv6addresspool": "ipv6addresspool",
}

# Dotted paths (within a sub-interface payload) that hold an object reference
# shaped like {"id": ..., "type": ..., "name": ...}.
REFERENCE_FIELD_PATHS: Tuple[Tuple[str, ...], ...] = (
    ("securityZone",),
    ("macAddressPool",),
    ("ipv4", "static", "pool"),
    ("ipv4", "static", "addressVariable"),
    ("ipv6", "pool"),
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the input export file and target device."""
    parser = argparse.ArgumentParser(
        description="Import FTD sub-interfaces exported as JSON from a source FMC into a destination FTD."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the JSON file containing exported sub-interface definitions.",
    )
    parser.add_argument(
        "--device-uuid",
        dest="device_uuid",
        default=None,
        help="UUID of the destination FTD device. Defaults to DST_FTD_UUID in this script.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# JSON parsing / validation
# ---------------------------------------------------------------------------

def load_subinterfaces_from_json(filepath: Path) -> List[Dict[str, Any]]:
    """
    Load exported sub-interface definitions from a JSON file.

    Accepts either a plain JSON array or a paged FMC GET response of the
    form {"items": [...], "paging": {...}}.

    Args:
        filepath (Path): Path to the exported JSON file.

    Returns:
        List[Dict[str, Any]]: Sub-interface definitions.

    Raises:
        SystemExit: If the file is missing, unreadable, or malformed.
    """
    try:
        with open(filepath, mode="r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error("Input JSON file not found: '%s'.", filepath)
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON file '%s': %s", filepath, e)
        raise SystemExit(1)

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]

    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        logger.error(
            "Unexpected JSON structure in '%s': expected a list of sub-interface objects.", filepath
        )
        raise SystemExit(1)

    logger.info("Loaded %d sub-interface record(s) from '%s'.", len(data), filepath.name)
    return data


def validate_record(rec: Dict[str, Any], rec_desc: str) -> List[str]:
    """Return the names of required fields that are missing/empty on *rec*."""
    return [f for f in REQUIRED_FIELDS if rec.get(f) in (None, "")]


# ---------------------------------------------------------------------------
# Destination lookups
# ---------------------------------------------------------------------------

class DestinationObjectCache:
    """
    Per-run cache of destination-FMC objects, keyed by fmc.object.* client
    attribute name. A full listing is fetched once per object type instead
    of once per lookup, so repeated references resolve in O(1).
    """

    def __init__(self, fmc: Any) -> None:
        self.fmc = fmc
        self._by_attr: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def _ensure_loaded(self, client_attr: str) -> Dict[str, Dict[str, Any]]:
        if client_attr not in self._by_attr:
            client = getattr(self.fmc.object, client_attr)
            try:
                items = client.get() or []
            except Exception:
                logger.exception("Failed to list destination '%s' objects.", client_attr)
                items = []
            if isinstance(items, dict):
                items = [items]
            self._by_attr[client_attr] = {item["name"]: item for item in items if item.get("name")}
            logger.info("Cached %d destination '%s' object(s).", len(self._by_attr[client_attr]), client_attr)
        return self._by_attr[client_attr]

    def lookup(self, client_attr: str, name: str) -> Optional[Dict[str, Any]]:
        """Return the destination object with the given name, or None if not present."""
        return self._ensure_loaded(client_attr).get(name)


def load_destination_parent_interfaces(fmc: Any, device_uuid: str) -> Dict[str, str]:
    """
    Return {interface_name: interface_id} for every physical and EtherChannel
    interface on the destination FTD. Sub-interfaces attach to a parent by
    name (not UUID) in the FMC API, so this is used to validate that the
    parent exists on the destination device before a sub-interface is created.

    Args:
        fmc: Authenticated destination FMC client instance.
        device_uuid (str): UUID of the destination FTD device.

    Returns:
        Dict[str, str]: Parent interface name -> destination interface UUID.
    """
    names: Dict[str, str] = {}
    for label, client in (
        ("physical", fmc.device.devicerecord.physicalinterface),
        ("EtherChannel", fmc.device.devicerecord.etherchannelinterface),
    ):
        try:
            items = client.get(container_uuid=device_uuid) or []
        except Exception:
            logger.exception("Failed to list destination %s interfaces.", label)
            items = []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            if item.get("name"):
                names[item["name"]] = item.get("id", "")
    return names


# ---------------------------------------------------------------------------
# Object reference resolution
# ---------------------------------------------------------------------------

def _get_nested(d: Dict[str, Any], path: Tuple[str, ...]) -> Optional[Any]:
    """Return the value at *path* within nested dicts, or None if any segment is absent."""
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _set_nested(d: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    """Set *value* at *path* within nested dicts, creating intermediate dicts as needed."""
    cur = d
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


def resolve_reference(
    cache: DestinationObjectCache,
    ref: Dict[str, Any],
    field_label: str,
    rec_desc: str,
    missing: List[Tuple[str, str]],
) -> Optional[Dict[str, str]]:
    """
    Resolve a source-FMC object reference ({'id', 'type', optional 'name'}) to
    its destination-FMC equivalent by looking it up by name.

    Args:
        cache (DestinationObjectCache): Destination-FMC object cache.
        ref (Dict[str, Any]): Object reference from the exported sub-interface.
        field_label (str): Dotted field path this reference came from (for logging).
        rec_desc (str): Human-readable sub-interface identifier (for logging).
        missing (List[Tuple[str, str]]): Accumulator for (type, name) pairs that failed.

    Returns:
        Optional[Dict[str, str]]: {'id', 'type', 'name'} for the destination object, or None.
    """
    obj_type = ref.get("type")
    obj_name = ref.get("name")
    src_id = ref.get("id")

    if not obj_type:
        logger.error("[%s] Field '%s' is missing 'type': %s", rec_desc, field_label, ref)
        missing.append(("Unknown", obj_name or "<unknown>"))
        return None

    if not obj_name:
        logger.error(
            "[%s] Field '%s' (%s, source id=%s) has no 'name' in the exported JSON; "
            "cannot resolve a source-FMC id without a name.",
            rec_desc, field_label, obj_type, src_id,
        )
        missing.append((obj_type, "<no name in export>"))
        return None

    client_attr = REFERENCE_TYPE_TO_CLIENT_ATTR.get(obj_type.lower())
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

    logger.info(
        "[%s] Resolved %s '%s': source id=%s -> destination id=%s.",
        rec_desc, obj_type, obj_name, src_id, found["id"],
    )
    return {"id": found["id"], "type": found.get("type", obj_type), "name": found.get("name", obj_name)}


# ---------------------------------------------------------------------------
# Payload transformation
# ---------------------------------------------------------------------------

def build_subinterface_payload(
    cache: DestinationObjectCache,
    parent_names: Dict[str, str],
    rec: Dict[str, Any],
    rec_desc: str,
) -> Tuple[Optional[Dict[str, Any]], List[Tuple[str, str]]]:
    """
    Build a POST-ready payload for a single sub-interface.

    Resolves the parent interface and every embedded object reference against
    the destination FMC, replacing source-FMC UUIDs with destination UUIDs.

    Args:
        cache (DestinationObjectCache): Destination-FMC object cache.
        parent_names (Dict[str, str]): Destination parent interface name -> UUID.
        rec (Dict[str, Any]): Source sub-interface record.
        rec_desc (str): Human-readable sub-interface identifier (for logging).

    Returns:
        Tuple[Optional[Dict[str, Any]], List[Tuple[str, str]]]:
            (payload, missing) -- payload is None if the parent interface or a
            referenced object could not be resolved; missing lists every
            (type, name) pair that failed to resolve, including the special
            type "ParentInterface" for an unresolved parent.
    """
    missing: List[Tuple[str, str]] = []

    parent_name = rec.get("name")
    if parent_name not in parent_names:
        logger.error(
            "[%s] Parent interface '%s' not found on destination FTD -- skipping.",
            rec_desc, parent_name,
        )
        missing.append(("ParentInterface", parent_name or "<missing>"))
        return None, missing

    logger.info(
        "[%s] Parent interface '%s' resolved on destination FTD (id=%s).",
        rec_desc, parent_name, parent_names[parent_name],
    )

    payload: Dict[str, Any] = copy.deepcopy(
        {key: value for key, value in rec.items() if key not in _READONLY_FIELDS}
    )

    ok = True
    for path in REFERENCE_FIELD_PATHS:
        ref = _get_nested(payload, path)
        if not ref or not isinstance(ref, dict) or not ref.get("id"):
            continue  # field not used on this sub-interface

        field_label = ".".join(path)
        resolved = resolve_reference(cache, ref, field_label, rec_desc, missing)
        if resolved is None:
            ok = False
            continue
        _set_nested(payload, path, resolved)

    if not ok:
        return None, missing

    return payload, missing


# ---------------------------------------------------------------------------
# Sub-interface creation
# ---------------------------------------------------------------------------

@dataclass
class ImportResult:
    total: int = 0
    created: int = 0
    failed: int = 0
    missing_objects: Set[Tuple[str, str]] = field(default_factory=set)
    missing_parents: Set[str] = field(default_factory=set)


def create_subinterface(fmc: Any, device_uuid: str, payload: Dict[str, Any], rec_desc: str) -> bool:
    """
    POST a single resolved sub-interface payload to the destination FTD.

    Args:
        fmc: Authenticated destination FMC client instance.
        device_uuid (str): UUID of the destination FTD device.
        payload (Dict[str, Any]): Fully resolved sub-interface payload.
        rec_desc (str): Human-readable sub-interface identifier (for logging).

    Returns:
        bool: True if the sub-interface was created successfully.
    """
    try:
        response = fmc.device.devicerecord.subinterface.create(
            data=payload,
            container_uuid=device_uuid,
        )
    except Exception:
        logger.exception("[%s] Request failed while creating sub-interface.", rec_desc)
        return False

    if response.status_code in (200, 201, 202):
        logger.info("[%s] Created successfully.", rec_desc)
        return True

    logger.error(
        "[%s] Failed to create (HTTP %d): %s",
        rec_desc, response.status_code, response.text[:500],
    )
    return False


def process_subinterfaces(fmc_dst: Any, device_uuid: str, records: List[Dict[str, Any]]) -> ImportResult:
    """
    Resolve and create every sub-interface record on the destination FTD,
    skipping (and reporting) any record whose dependencies cannot be resolved.
    """
    result = ImportResult(total=len(records))
    cache = DestinationObjectCache(fmc_dst)

    logger.info("Loading parent interfaces from destination FTD %s ...", device_uuid)
    parent_names = load_destination_parent_interfaces(fmc_dst, device_uuid)
    logger.info("Destination FTD has %d candidate parent interface(s).", len(parent_names))
    if not parent_names:
        logger.warning(
            "No physical/EtherChannel interfaces found on destination FTD %s; "
            "every sub-interface will fail parent resolution.", device_uuid,
        )

    for index, rec in enumerate(records, start=1):
        sub_name = rec.get("ifname") or rec.get("name") or f"#{index}"
        rec_desc = f"Sub-interface #{index} ('{sub_name}', VLAN {rec.get('vlanId', '?')})"
        logger.info("Processing %s ...", rec_desc)

        missing_fields = validate_record(rec, rec_desc)
        if missing_fields:
            logger.error(
                "[%s] Missing required field(s) in source record: %s -- skipping.",
                rec_desc, ", ".join(missing_fields),
            )
            result.failed += 1
            continue

        payload, missing = build_subinterface_payload(cache, parent_names, rec, rec_desc)
        for obj_type, obj_name in missing:
            if obj_type == "ParentInterface":
                result.missing_parents.add(obj_name)
            else:
                result.missing_objects.add((obj_type, obj_name))

        if payload is None:
            logger.error("[%s] Skipped: one or more dependencies could not be resolved.", rec_desc)
            result.failed += 1
            continue

        if create_subinterface(fmc_dst, device_uuid, payload, rec_desc):
            result.created += 1
        else:
            result.failed += 1

    return result


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(result: ImportResult) -> None:
    logger.info("=" * 78)
    logger.info("Import Summary")
    logger.info("  Total processed          : %d", result.total)
    logger.info("  Successfully imported     : %d", result.created)
    logger.info("  Failed                    : %d", result.failed)

    if result.missing_parents:
        logger.info("  Missing parent interfaces : %d", len(result.missing_parents))
        for name in sorted(result.missing_parents):
            logger.info("    - %s", name)
    else:
        logger.info("  Missing parent interfaces : none")

    if result.missing_objects:
        logger.info("  Missing referenced objects: %d", len(result.missing_objects))
        for obj_type, obj_name in sorted(result.missing_objects):
            logger.info("    - %s '%s'", obj_type, obj_name)
    else:
        logger.info("  Missing referenced objects: none")
    logger.info("=" * 78)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    1. Load and validate sub-interface definitions from the input JSON file.
    2. Connect to the destination FMC.
    3. Resolve each sub-interface's parent interface and object references by
       name against the destination FMC, then create it.
    4. Print an import summary.
    """
    args = parse_args()
    device_uuid = args.device_uuid or DST_FTD_UUID
    if device_uuid == "REPLACE_WITH_DESTINATION_FTD_UUID":
        logger.error("No destination FTD UUID provided. Pass --device-uuid or set DST_FTD_UUID.")
        raise SystemExit(1)

    records = load_subinterfaces_from_json(args.input)
    if not records:
        logger.warning("No sub-interface records found in '%s'. Nothing to do.", args.input)
        raise SystemExit(0)

    logger.info("Enter credentials for the destination FMC.")
    credentials = utils.prompt_fmc_credentials()
    fmc_dst = utils.fmc_connect(*credentials)

    result = process_subinterfaces(fmc_dst, device_uuid, records)
    print_summary(result)

    fmc_dst.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
