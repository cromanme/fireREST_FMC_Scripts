#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_ftd_ipv4_static_routes_different_fmcs.py

Reads a CSV file of IPv4 static routes exported by
export_ipv4_static_routes_to_csv.py from a SOURCE FMC and recreates them on a
target FTD managed by a DIFFERENT (destination) FMC.

This is a cross-FMC variant of create_ipv4static_routes_from_csv.py: none of
the object UUIDs embedded in the export are valid on the destination FMC, so
every referenced object (Gateway host, Selected Networks) is looked up by
name/type on the destination FMC and rewritten with the destination UUID
before the route is created. The egress interface is matched by name only
(FMC references interfaces by name, not UUID, on a static route) and is
validated to exist on the destination FTD.

Usage:
    Run this script directly. It will prompt for destination FMC credentials.
    Set FTD_UUID to the destination device UUID and CSV_FILENAME to the
    export produced by export_ipv4_static_routes_to_csv.py.

CSV format (header row, as produced by export_ipv4_static_routes_to_csv.py):
    VRF, Route_UUID, Interface, Gateway, Metric, Selected NetworksJSON

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Note:
    For devices in HA/Cluster, use the UUID of the Active/Control unit.
    'Route_UUID' and 'VRF' are read-only metadata from the export and are
    not used to build the create payload.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FTD_UUID: str = "REPLACE_WITH_DESTINATION_FTD_UUID"
CSV_FILENAME: str = "../output/ftd_ipv4_static_routes.csv"
BULK_CHUNK_SIZE: int = 1000  # max routes per bulk API request

# Source-FMC object 'type' (as embedded in Selected NetworksJSON) -> fmc.object.<attr>
# on the destination FMC. selectedNetworks may reference any of these types.
NETWORK_OBJECT_TYPE_TO_CLIENT_ATTR: Dict[str, str] = {
    "host": "host",
    "network": "network",
    "networkgroup": "networkgroup",
    "range": "range",
    "fqdn": "fqdn",
}


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def read_routes_from_csv(filename: str) -> List[Dict[str, str]]:
    """
    Read the IPv4 static route export CSV and return a list of row dicts.

    Args:
        filename (str): Path to the CSV file produced by
            export_ipv4_static_routes_to_csv.py.

    Returns:
        List[Dict[str, str]]: Parsed rows.

    Raises:
        SystemExit: If the file is not found or cannot be read.
    """
    try:
        with open(filename, mode="r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except FileNotFoundError:
        logger.error("CSV file not found: '%s'.", filename)
        raise SystemExit(1)
    except Exception as e:
        logger.error("Failed to read CSV file '%s': %s", filename, e)
        raise SystemExit(1)


def parse_selected_networks(raw: str, rec_desc: str) -> Optional[List[Dict[str, Any]]]:
    """
    Parse the 'Selected NetworksJSON' column into a list of source-FMC object references.

    Args:
        raw (str): Raw JSON string from the CSV cell.
        rec_desc (str): Human-readable route identifier (for logging).

    Returns:
        Optional[List[Dict[str, Any]]]: Parsed references, or None if empty/malformed.
    """
    raw = (raw or "").strip()
    if not raw:
        logger.error("[%s] 'Selected NetworksJSON' is empty.", rec_desc)
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("[%s] Failed to parse 'Selected NetworksJSON': %s", rec_desc, e)
        return None
    if not isinstance(parsed, list) or not parsed:
        logger.error("[%s] 'Selected NetworksJSON' must be a non-empty list of objects.", rec_desc)
        return None
    return parsed


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


def load_destination_interfaces(fmc: Any, device_uuid: str) -> Dict[str, str]:
    """
    Return {interface_name: interface_id} for every physical, EtherChannel and
    sub-interface on the destination FTD. A static route references its
    egress interface by name (not UUID) in the FMC API, so this is used only
    to validate that the interface exists on the destination device.

    Args:
        fmc: Authenticated destination FMC client instance.
        device_uuid (str): UUID of the destination FTD device.

    Returns:
        Dict[str, str]: Interface name -> destination interface UUID.
    """
    names: Dict[str, str] = {}
    for label, client in (
        ("physical", fmc.device.devicerecord.physicalinterface),
        ("EtherChannel", fmc.device.devicerecord.etherchannelinterface),
        ("sub-interface", fmc.device.devicerecord.subinterface),
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

def resolve_object_reference(
    cache: DestinationObjectCache,
    obj_ref: Dict[str, Any],
    field_label: str,
    rec_desc: str,
    missing: List[Tuple[str, str]],
) -> Optional[Dict[str, str]]:
    """
    Resolve a source-FMC object reference ({'id', 'type', 'name'}) to its
    destination-FMC equivalent by looking it up by name.

    Args:
        cache (DestinationObjectCache): Destination-FMC object cache.
        obj_ref (Dict[str, Any]): Object reference embedded in the exported CSV.
        field_label (str): Field this reference came from (for logging).
        rec_desc (str): Human-readable route identifier (for logging).
        missing (List[Tuple[str, str]]): Accumulator for (type, name) pairs that failed.

    Returns:
        Optional[Dict[str, str]]: {'id', 'type', 'name'} for the destination object, or None.
    """
    obj_type = obj_ref.get("type")
    obj_name = obj_ref.get("name")
    src_id = obj_ref.get("id")

    if not obj_type or not obj_name:
        logger.error("[%s] Field '%s' is missing 'type' or 'name': %s", rec_desc, field_label, obj_ref)
        missing.append((obj_type or "Unknown", obj_name or "<unknown>"))
        return None

    client_attr = NETWORK_OBJECT_TYPE_TO_CLIENT_ATTR.get(obj_type.lower())
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


def resolve_gateway(
    cache: DestinationObjectCache, gateway_name: str, rec_desc: str, missing: List[Tuple[str, str]]
) -> Optional[Dict[str, str]]:
    """Resolve the route's gateway (always a Host object per the FMC schema) by name."""
    gateway_name = (gateway_name or "").strip()
    if not gateway_name:
        logger.error("[%s] Missing 'Gateway' name in source row.", rec_desc)
        missing.append(("Host", "<missing>"))
        return None
    return resolve_object_reference(cache, {"type": "Host", "name": gateway_name}, "gateway", rec_desc, missing)


# ---------------------------------------------------------------------------
# Payload generation
# ---------------------------------------------------------------------------

def build_route_payload(interface: str, selected_nets: List[Dict[str, str]], gateway_obj: Dict[str, str]) -> Dict[str, Any]:
    """
    Build an IPv4 static route creation payload from resolved destination-FMC references.

    Args:
        interface (str): Egress interface name (validated to exist on the destination FTD).
        selected_nets (List[Dict[str, str]]): Destination-FMC network/host/group references.
        gateway_obj (Dict[str, str]): Destination-FMC gateway host reference.

    Returns:
        Dict[str, Any]: Payload suitable for POSTing to FMC.
    """
    return {
        "interfaceName":    interface,
        "selectedNetworks": selected_nets,
        "gateway":          {"object": gateway_obj},
        "metricValue":      1,
        "type":             "IPv4StaticRoute",
        "isTunneled":       False,
    }


def process_row(
    index: int,
    row: Dict[str, str],
    cache: DestinationObjectCache,
    interface_names: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], List[Tuple[str, str]]]:
    """
    Resolve a single CSV row into a route payload ready for creation on the
    destination FTD.

    Args:
        index (int): 1-based row number (for logging).
        row (Dict[str, str]): CSV row as produced by export_ipv4_static_routes_to_csv.py.
        cache (DestinationObjectCache): Destination-FMC object cache.
        interface_names (Dict[str, str]): Destination interface name -> UUID.

    Returns:
        Tuple[Optional[Dict[str, Any]], List[Tuple[str, str]]]:
            (payload, missing) -- payload is None if the egress interface or a
            referenced object could not be resolved; missing lists every
            (type, name) pair that failed to resolve.
    """
    missing: List[Tuple[str, str]] = []
    interface = (row.get("Interface") or "").strip()
    gateway_name = (row.get("Gateway") or "").strip()
    rec_desc = f"Route #{index} (interface='{interface}', gateway='{gateway_name}')"

    logger.info("Processing %s ...", rec_desc)

    if not interface:
        logger.error("[%s] Missing required field 'Interface'.", rec_desc)
        missing.append(("Interface", "<missing>"))
        return None, missing

    if interface not in interface_names:
        logger.error(
            "[%s] Egress interface '%s' not found on destination FTD -- skipping.",
            rec_desc, interface,
        )
        missing.append(("Interface", interface))
        return None, missing

    logger.info(
        "[%s] Egress interface '%s' resolved on destination FTD (id=%s).",
        rec_desc, interface, interface_names[interface],
    )

    net_refs = parse_selected_networks(row.get("Selected NetworksJSON", ""), rec_desc)
    if net_refs is None:
        missing.append(("SelectedNetworks", "<malformed>"))
        return None, missing

    ok = True
    selected_nets: List[Dict[str, str]] = []
    for ref in net_refs:
        if not isinstance(ref, dict):
            logger.error("[%s] Invalid entry in 'Selected NetworksJSON': %r", rec_desc, ref)
            missing.append(("Unknown", "<invalid entry>"))
            ok = False
            continue
        resolved = resolve_object_reference(cache, ref, "selectedNetworks[]", rec_desc, missing)
        if resolved is None:
            ok = False
        else:
            selected_nets.append(resolved)

    gateway_obj = resolve_gateway(cache, gateway_name, rec_desc, missing)
    if gateway_obj is None:
        ok = False

    if not ok:
        return None, missing

    return build_route_payload(interface, selected_nets, gateway_obj), missing


# ---------------------------------------------------------------------------
# Route creation
# ---------------------------------------------------------------------------

@dataclass
class ImportResult:
    total: int = 0
    created: int = 0
    failed: int = 0
    missing_objects: Set[Tuple[str, str]] = field(default_factory=set)


def create_routes_in_bulk(
    fmc: Any, device_uuid: str, payloads: List[Dict[str, Any]], result: ImportResult
) -> None:
    """
    Create resolved route payloads on the destination FTD via bulk POST,
    chunked to BULK_CHUNK_SIZE per request.
    """
    for i in range(0, len(payloads), BULK_CHUNK_SIZE):
        chunk = payloads[i : i + BULK_CHUNK_SIZE]
        logger.info(
            "Bulk creating routes %d-%d of %d ...",
            i + 1, i + len(chunk), len(payloads),
        )
        try:
            # Passing a list triggers ?bulk=true automatically in fireREST.
            response = fmc.device.devicerecord.routing.ipv4staticroute.create(
                data=chunk,
                container_uuid=device_uuid,
            )
            if response.status_code in (200, 201, 202):
                result.created += len(chunk)
                logger.info("Bulk created %d route(s) successfully.", len(chunk))
            else:
                result.failed += len(chunk)
                logger.error(
                    "Bulk create failed (HTTP %d): %s",
                    response.status_code, response.text[:500],
                )
        except Exception:
            result.failed += len(chunk)
            logger.exception("Bulk create request failed for chunk of %d route(s).", len(chunk))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(result: ImportResult) -> None:
    logger.info("=" * 78)
    logger.info("Import Summary")
    logger.info("  Total processed           : %d", result.total)
    logger.info("  Successfully imported      : %d", result.created)
    logger.info("  Failed                     : %d", result.failed)

    if result.missing_objects:
        logger.info("  Missing referenced objects : %d", len(result.missing_objects))
        for obj_type, obj_name in sorted(result.missing_objects):
            logger.info("    - %s '%s'", obj_type, obj_name)
    else:
        logger.info("  Missing referenced objects : none")
    logger.info("=" * 78)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    1. Read the IPv4 static route export CSV.
    2. Connect to the destination FMC.
    3. Resolve each route's egress interface, gateway, and selected networks
       by name against the destination FMC.
    4. Bulk-create the resolved routes on the destination FTD.
    5. Print an import summary.
    """
    if FTD_UUID == "REPLACE_WITH_DESTINATION_FTD_UUID":
        logger.error("Set FTD_UUID to the destination FTD device UUID before running this script.")
        raise SystemExit(1)

    logger.info("Enter credentials for the destination FMC.")
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    rows = read_routes_from_csv(CSV_FILENAME)
    if not rows:
        logger.warning("No rows found in '%s'. Nothing to do.", CSV_FILENAME)
        fmc.conn.session.close()
        raise SystemExit(0)

    result = ImportResult(total=len(rows))
    cache = DestinationObjectCache(fmc)

    logger.info("Loading interfaces from destination FTD %s ...", FTD_UUID)
    interface_names = load_destination_interfaces(fmc, FTD_UUID)
    logger.info("Destination FTD has %d candidate egress interface(s).", len(interface_names))
    if not interface_names:
        logger.warning(
            "No interfaces found on destination FTD %s; every route will fail interface resolution.",
            FTD_UUID,
        )

    payloads: List[Dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        payload, missing = process_row(index, row, cache, interface_names)
        result.missing_objects.update(missing)
        if payload is None:
            result.failed += 1
        else:
            payloads.append(payload)

    if payloads:
        logger.info("Prepared %d route payload(s) for bulk creation.", len(payloads))
        create_routes_in_bulk(fmc, FTD_UUID, payloads, result)
    else:
        logger.warning("No valid route payloads could be built. Nothing to create.")

    print_summary(result)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
