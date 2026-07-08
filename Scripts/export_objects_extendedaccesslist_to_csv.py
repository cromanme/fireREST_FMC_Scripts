#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_objects_extendedaccesslist_to_csv.py

Connects to a Cisco FMC and exports all Extended Access List objects to a
timestamped CSV file, along with one additional CSV per network/port object
type referenced by any Access Control Entry (ACE).

Object references (sourceNetworks, destinationNetworks, sourcePorts,
destinationPorts) are resolved from UUID to object name before being written
to the main CSV; the raw UUIDs are never exported. Literal values (e.g. a
bare IP address or a port/protocol pair) are written as-is.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    CSV files are written to OUTPUT_DIR.

Outputs (created in OUTPUT_DIR):
    - fmc_extendedaccesslists_YYYYMMDD-HHMMSS.csv
      -> aclId,aclName,aclDescription,entryIndex,action,logLevel,logging,
         logInterval,sourceNetworksJSON,destinationNetworksJSON,
         sourcePortsJSON,destinationPortsJSON
    - fmc_<type>s_YYYYMMDD-HHMMSS.csv (one per referenced object type, e.g.
      fmc_hosts_*, fmc_networks_*, fmc_networkgroups_*,
      fmc_protocolportobjects_*, fmc_portobjectgroups_*)
      -> id,name,type,value,protocol,port,memberCount,membersJSON,
         description,detailsJSON

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

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

OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent / "output"

NETWORK_FIELDS: Tuple[str, ...] = ("sourceNetworks", "destinationNetworks")
PORT_FIELDS: Tuple[str, ...] = ("sourcePorts", "destinationPorts")

REFERENCE_FIELDNAMES: List[str] = [
    "id", "name", "type", "value", "protocol", "port",
    "memberCount", "membersJSON", "description", "detailsJSON",
]

# Fields already surfaced as dedicated columns in the reference object CSV;
# anything else on the raw object is captured in 'detailsJSON' instead.
_REFERENCE_KNOWN_FIELDS = {
    "id", "name", "type", "value", "protocol", "port", "description",
    "objects", "literals", "links", "metadata", "overrides", "version",
    "overridable", "overrideTargetId",
}


# ---------------------------------------------------------------------------
# Object reference resolution
# ---------------------------------------------------------------------------

def collect_referenced_objects(acls: List[Dict]) -> Dict[str, Set[str]]:
    """
    Scan every ACE in every Extended Access List and collect the distinct
    (type, id) pairs referenced by sourceNetworks/destinationNetworks/
    sourcePorts/destinationPorts.

    Args:
        acls (List[Dict]): Extended Access List objects (with entries).

    Returns:
        Dict[str, Set[str]]: Referenced object ids, keyed by FMC object type.
    """
    refs: Dict[str, Set[str]] = {}
    for acl in acls:
        for entry in acl.get("entries") or []:
            for field in NETWORK_FIELDS + PORT_FIELDS:
                container = entry.get(field) or {}
                for obj in container.get("objects") or []:
                    obj_type = obj.get("type")
                    obj_id = obj.get("id")
                    if obj_type and obj_id:
                        refs.setdefault(obj_type, set()).add(obj_id)
    return refs


def resolve_referenced_objects(fmc, refs: Dict[str, Set[str]]) -> Dict[str, Dict[str, Dict]]:
    """
    Fetch the full object for every referenced (type, id) pair.

    One 'get all' call is issued per object type (reusing the fireREST
    resource matching the FMC type name, e.g. 'NetworkGroup' -> object.networkgroup)
    instead of one call per individual UUID.

    Args:
        fmc: Authenticated FMC client instance.
        refs (Dict[str, Set[str]]): Referenced object ids, keyed by FMC object type.

    Returns:
        Dict[str, Dict[str, Dict]]: Resolved objects, keyed by [type][id].
    """
    resolved: Dict[str, Dict[str, Dict]] = {}
    for obj_type, ids in refs.items():
        attr = obj_type.lower()
        resource = getattr(fmc.object, attr, None)
        if resource is None:
            logger.warning(
                "No fireREST resource found for object type '%s'. %d id(s) will remain unresolved.",
                obj_type, len(ids),
            )
            continue
        try:
            objects: List[Dict] = resource.get()
        except Exception as e:
            logger.error("Failed to retrieve '%s' objects: %s", obj_type, e)
            continue

        by_id = {o.get("id"): o for o in objects if o.get("id") in ids}
        resolved[obj_type] = by_id

        missing = ids - by_id.keys()
        if missing:
            logger.warning("Could not resolve %d '%s' object id(s): %s", len(missing), obj_type, missing)

    return resolved


def resolve_name(resolved: Dict[str, Dict[str, Dict]], obj_type: str, obj_id: str) -> str:
    """
    Resolve a single object reference to its name.

    Args:
        resolved (Dict[str, Dict[str, Dict]]): Objects resolved by resolve_referenced_objects().
        obj_type (str): FMC object type (e.g. 'Host', 'NetworkGroup').
        obj_id (str): Object UUID.

    Returns:
        str: Object name, or a placeholder if it could not be resolved.
    """
    obj = resolved.get(obj_type, {}).get(obj_id)
    if obj and obj.get("name"):
        return obj["name"]
    return f"UNRESOLVED:{obj_type}:{obj_id}"


def build_network_list(container: Dict, resolved: Dict[str, Dict[str, Dict]]) -> List[str]:
    """
    Convert a sourceNetworks/destinationNetworks container into a flat list
    of display strings (literal values as-is, object references resolved to names).
    """
    values: List[str] = []
    for lit in container.get("literals") or []:
        values.append(lit.get("value", ""))
    for obj in container.get("objects") or []:
        values.append(resolve_name(resolved, obj.get("type"), obj.get("id")))
    return values


def build_port_list(container: Dict, resolved: Dict[str, Dict[str, Dict]]) -> List[str]:
    """
    Convert a sourcePorts/destinationPorts container into a flat list of
    display strings (literal port/protocol pairs as-is, object references
    resolved to names).
    """
    values: List[str] = []
    for lit in container.get("literals") or []:
        port = lit.get("port", "")
        protocol = lit.get("protocol", "")
        values.append(f"{port}/{protocol}" if protocol else port)
    for obj in container.get("objects") or []:
        values.append(resolve_name(resolved, obj.get("type"), obj.get("id")))
    return values


# ---------------------------------------------------------------------------
# CSV export helpers
# ---------------------------------------------------------------------------

def export_extendedaccesslists(fmc, ts: str) -> Tuple[str, Dict[str, Dict[str, Dict]]]:
    """
    Export all Extended Access List ACEs to a CSV file, one row per entry.

    Args:
        fmc: Authenticated FMC client instance.
        ts (str): Timestamp string used in the output filename.

    Returns:
        Tuple[str, Dict[str, Dict[str, Dict]]]: Path to the written CSV file
        (or "" on failure), and the resolved reference objects keyed by
        [type][id] for reuse when exporting the per-type reference CSVs.
    """
    try:
        acls: List[Dict] = fmc.object.extendedaccesslist.get()
    except Exception as e:
        logger.error("Failed to retrieve Extended Access List objects: %s", e)
        return "", {}

    refs = collect_referenced_objects(acls)
    resolved = resolve_referenced_objects(fmc, refs)

    rows: List[Dict] = []
    for acl in acls:
        for index, entry in enumerate(acl.get("entries") or []):
            rows.append({
                "aclId":                   acl.get("id", ""),
                "aclName":                 acl.get("name", ""),
                "aclDescription":          acl.get("description", ""),
                "entryIndex":              index,
                "action":                  entry.get("action", ""),
                "logLevel":                entry.get("logLevel", ""),
                "logging":                 entry.get("logging", ""),
                "logInterval":             entry.get("logInterval", ""),
                "sourceNetworksJSON":      json.dumps(build_network_list(entry.get("sourceNetworks") or {}, resolved), ensure_ascii=False),
                "destinationNetworksJSON": json.dumps(build_network_list(entry.get("destinationNetworks") or {}, resolved), ensure_ascii=False),
                "sourcePortsJSON":         json.dumps(build_port_list(entry.get("sourcePorts") or {}, resolved), ensure_ascii=False),
                "destinationPortsJSON":    json.dumps(build_port_list(entry.get("destinationPorts") or {}, resolved), ensure_ascii=False),
            })

    path = OUTPUT_DIR / f"fmc_extendedaccesslists_{ts}.csv"
    utils.write_csv(
        str(path),
        rows,
        [
            "aclId", "aclName", "aclDescription", "entryIndex", "action", "logLevel", "logging", "logInterval",
            "sourceNetworksJSON", "destinationNetworksJSON", "sourcePortsJSON", "destinationPortsJSON",
        ],
    )
    logger.info("Extended Access Lists exported: %d ACL(s), %d entrie(s) -> %s", len(acls), len(rows), path)
    return str(path), resolved


def build_reference_row(obj: Dict) -> Dict:
    """
    Build a single CSV row for a referenced network/port object.

    Group-like objects (Network Group, Port Object Group) have their members
    serialized as a JSON string in 'membersJSON', mirroring how Network Group
    members are exported elsewhere in this project. Any remaining
    type-specific fields are captured in 'detailsJSON'.

    Args:
        obj (Dict): Full object definition, as returned by FMC.

    Returns:
        Dict: Row ready to be written via utils.write_csv().
    """
    members: List[Dict] = []
    for member in obj.get("objects") or []:
        members.append({"refType": member.get("type"), "id": member.get("id"), "name": member.get("name")})
    for literal in obj.get("literals") or []:
        members.append({"refType": literal.get("type"), "value": literal.get("value")})

    extra = {k: v for k, v in obj.items() if k not in _REFERENCE_KNOWN_FIELDS}

    return {
        "id":          obj.get("id", ""),
        "name":        obj.get("name", ""),
        "type":        obj.get("type", ""),
        "value":       obj.get("value", ""),
        "protocol":    obj.get("protocol", ""),
        "port":        obj.get("port", ""),
        "memberCount": len(members),
        "membersJSON": json.dumps(members, ensure_ascii=False) if members else "",
        "description": obj.get("description", ""),
        "detailsJSON": json.dumps(extra, ensure_ascii=False) if extra else "",
    }


def export_referenced_objects(resolved: Dict[str, Dict[str, Dict]], ts: str) -> List[str]:
    """
    Export one CSV per referenced FMC object type, with duplicates removed.

    Args:
        resolved (Dict[str, Dict[str, Dict]]): Objects resolved by resolve_referenced_objects().
        ts (str): Timestamp string used in the output filenames.

    Returns:
        List[str]: Paths to the written CSV files.
    """
    paths: List[str] = []
    for obj_type, by_id in resolved.items():
        rows = [build_reference_row(obj) for obj in by_id.values()]
        path = OUTPUT_DIR / f"fmc_{obj_type.lower()}s_{ts}.csv"
        utils.write_csv(str(path), rows, REFERENCE_FIELDNAMES)
        logger.info("Referenced '%s' objects exported: %d -> %s", obj_type, len(rows), path)
        paths.append(str(path))
    return paths


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Connect to FMC and export all Extended Access List objects, plus every
    referenced network/port object, to CSV files.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    logger.info("Enter credentials for FMC.")
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    _, resolved = export_extendedaccesslists(fmc, ts)
    export_referenced_objects(resolved, ts)

    logger.info("CSV generated.")

    fmc.conn.session.close()
    logger.info("FMC session closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
