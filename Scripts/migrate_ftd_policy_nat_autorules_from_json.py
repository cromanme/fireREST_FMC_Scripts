#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_ftd_policy_nat_autorules_from_json.py

Migrates FTD Auto NAT rules exported from one FMC into an FTD NAT policy on
a different (destination) FMC. Since UUIDs are never portable across FMC
instances, every object referenced by a rule (Host, Network, Network Group,
Range, FQDN, Security Zone, Interface Group, PAT pool address, ...) is
looked up by name on the destination FMC and re-linked before the rule is
created there.

Usage:
    Run this script directly. It will prompt for destination FMC credentials.
    Set INPUT_JSON_FILE to the exported Auto NAT rules JSON (as produced by
    FMC/Policy/get_ftdnatpolicies_autonatrules.py) and DST_NAT_POLICY_UUID to
    the target FTD NAT policy UUID.

Input JSON Format:
    A JSON array of FTDAutoNatRule objects (or a paged GET response with an
    'items' array), as returned by:
    GET /api/fmc_config/v1/domain/{domainUUID}/policy/ftdnatpolicies/{containerUUID}/autonatrules

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from fireREST import exceptions as fireREST_exceptions

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

INPUT_JSON_FILE: str      = "/Users/cmendezm/Documents/GitHub/fireREST_FMC_Scripts/FMC/Responses/ftdnatpolicies_autonatrule.json"          # exported Auto NAT rules
DST_NAT_POLICY_UUID: str  = "005056A4-7A08-0ed3-0000-017179871078"     # target FTD NAT policy UUID

# Maps the object 'type' as recorded in the exported rule to the matching
# fireREST client attribute under fmc.object.
OBJECT_TYPE_TO_CLIENT_ATTR: Dict[str, str] = {
    "host": "host",
    "network": "network",
    "networkgroup": "networkgroup",
    "range": "range",
    "fqdn": "fqdn",
    "securityzone": "securityzone",
    "interfacegroup": "interfacegroup",
}

# Top-level FTDAutoNatRule scalar fields that can be copied through as-is.
SCALAR_FIELDS: Tuple[str, ...] = (
    "natType",
    "serviceProtocol",
    "originalPort",
    "translatedPort",
    "dns",
    "interfaceIpv6",
    "noProxyArp",
    "netToNet",
    "fallThrough",
    "routeLookup",
    "interfaceInTranslatedNetwork",
    "description",
)

# patOptions scalar fields that can be copied through as-is.
PAT_OPTION_SCALAR_FIELDS: Tuple[str, ...] = (
    "blockAllocation",
    "includeReserve",
    "flatPortRange",
    "interfacePat",
    "extendedPat",
    "roundRobin",
)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_autonatrules_from_json(filepath: str) -> List[Dict[str, Any]]:
    """
    Load exported Auto NAT rules from a JSON file.

    Accepts either a plain JSON array of rules or a paged FMC GET response
    of the form {"items": [...], "paging": {...}}.

    Args:
        filepath (str): Path to the exported JSON file.

    Returns:
        List[Dict[str, Any]]: Auto NAT rule definitions.

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
        logger.error("Unexpected JSON structure in '%s': expected a list of Auto NAT rules.", filepath)
        raise SystemExit(1)

    logger.info("Loaded %d Auto NAT Rule(s) from '%s'.", len(data), filepath)
    return data


# ---------------------------------------------------------------------------
# Object resolution
# ---------------------------------------------------------------------------

def describe_rule(rule: Dict[str, Any], index: int) -> str:
    """Build a human-readable identifier for a rule, used in log messages."""
    name = rule.get("name")
    if name:
        return f"Rule #{index} ('{name}')"

    original_name = (rule.get("originalNetwork") or {}).get("name", "?")
    translated_name = (rule.get("translatedNetwork") or {}).get("name")
    if translated_name:
        return f"Rule #{index} ({original_name} -> {translated_name})"
    return f"Rule #{index} ({original_name} -> <interface>)"


def _object_client_for_type(fmc: Any, obj_type: Optional[str]) -> Optional[Any]:
    """Return the fmc.object.* client that manages the given object type."""
    attr = OBJECT_TYPE_TO_CLIENT_ATTR.get((obj_type or "").lower())
    if attr is None:
        return None
    return getattr(fmc.object, attr, None)


def resolve_object(
    fmc_dst: Any,
    obj_ref: Dict[str, Any],
    field_label: str,
    rule_desc: str,
    missing: List[Tuple[str, str]],
) -> Optional[Dict[str, str]]:
    """
    Resolve a source-FMC object reference (type/name/id) to its destination-FMC
    equivalent by looking it up by name.

    Args:
        fmc_dst: Connected destination FMC client.
        obj_ref (Dict[str, Any]): Object reference from the exported rule.
        field_label (str): Name of the rule field this reference came from (for logging).
        rule_desc (str): Human-readable rule identifier (for logging).
        missing (List[Tuple[str, str]]): Accumulator for (type, name) pairs that could not be resolved.

    Returns:
        Optional[Dict[str, str]]: {"type", "id", "name"} for the destination object, or None on failure.
    """
    obj_type = obj_ref.get("type")
    obj_name = obj_ref.get("name")

    if not obj_type or not obj_name:
        logger.error("[%s] Field '%s' is missing 'type' or 'name' in source data: %s", rule_desc, field_label, obj_ref)
        missing.append((obj_type or "Unknown", obj_name or "Unknown"))
        return None

    client = _object_client_for_type(fmc_dst, obj_type)
    if client is None:
        logger.error(
            "[%s] Field '%s' references unsupported object type '%s' (object '%s').",
            rule_desc, field_label, obj_type, obj_name,
        )
        missing.append((obj_type, obj_name))
        return None

    logger.info("[%s] Looking up %s '%s' (field '%s') on destination FMC.", rule_desc, obj_type, obj_name, field_label)
    try:
        found = client.get(name=obj_name)
    except fireREST_exceptions.ResourceNotFoundError:
        logger.error(
            "[%s] Missing referenced object: %s '%s' (field '%s') not found on destination FMC.",
            rule_desc, obj_type, obj_name, field_label,
        )
        missing.append((obj_type, obj_name))
        return None
    except Exception:
        logger.exception(
            "[%s] Error looking up %s '%s' (field '%s') on destination FMC.",
            rule_desc, obj_type, obj_name, field_label,
        )
        missing.append((obj_type, obj_name))
        return None

    logger.info(
        "[%s] Resolved %s '%s': source id %s -> destination id %s",
        rule_desc, obj_type, obj_name, obj_ref.get("id", "?"), found["id"],
    )
    return {"type": found.get("type", obj_type), "id": found["id"], "name": found.get("name", obj_name)}


# ---------------------------------------------------------------------------
# Payload transformation
# ---------------------------------------------------------------------------

def build_autonatrule_payload(
    fmc_dst: Any,
    rule: Dict[str, Any],
    rule_desc: str,
    missing: List[Tuple[str, str]],
) -> Optional[Dict[str, Any]]:
    """
    Build a creation payload for a single Auto NAT rule, remapping every
    referenced object to its destination-FMC UUID.

    Args:
        fmc_dst: Connected destination FMC client.
        rule (Dict[str, Any]): Source rule definition from the exported JSON.
        rule_desc (str): Human-readable rule identifier (for logging).
        missing (List[Tuple[str, str]]): Accumulator for (type, name) pairs that could not be resolved.

    Returns:
        Optional[Dict[str, Any]]: Payload ready for create(), or None if a required object is missing.
    """
    payload: Dict[str, Any] = {"type": "FTDAutoNatRule"}
    for field in SCALAR_FIELDS:
        if field in rule:
            payload[field] = rule[field]

    if "natType" not in payload:
        logger.error("[%s] Missing required field 'natType' in source rule.", rule_desc)
        return None

    ok = True

    original_ref = rule.get("originalNetwork")
    if not original_ref:
        logger.error("[%s] Missing required field 'originalNetwork' in source rule.", rule_desc)
        ok = False
    else:
        resolved = resolve_object(fmc_dst, original_ref, "originalNetwork", rule_desc, missing)
        if resolved is None:
            ok = False
        else:
            payload["originalNetwork"] = resolved

    translated_ref = rule.get("translatedNetwork")
    if translated_ref:
        resolved = resolve_object(fmc_dst, translated_ref, "translatedNetwork", rule_desc, missing)
        if resolved is None:
            ok = False
        else:
            payload["translatedNetwork"] = resolved

    for field in ("sourceInterface", "destinationInterface"):
        ref = rule.get(field)
        if ref:
            resolved = resolve_object(fmc_dst, ref, field, rule_desc, missing)
            if resolved is None:
                ok = False
            else:
                payload[field] = resolved

    pat_options = rule.get("patOptions")
    if pat_options:
        new_pat_options: Dict[str, Any] = {}
        for field in PAT_OPTION_SCALAR_FIELDS:
            if field in pat_options:
                new_pat_options[field] = pat_options[field]

        pool_ref = pat_options.get("patPoolAddress")
        if pool_ref:
            resolved = resolve_object(fmc_dst, pool_ref, "patOptions.patPoolAddress", rule_desc, missing)
            if resolved is None:
                ok = False
            else:
                new_pat_options["patPoolAddress"] = resolved

        payload["patOptions"] = new_pat_options

    if not ok:
        return None
    return payload


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    1. Connect to the destination FMC.
    2. Load exported Auto NAT rules from the input JSON file.
    3. For each rule, resolve every referenced object on the destination FMC
       and create the equivalent rule in the target NAT policy.
    4. Print a migration summary.
    """
    logger.info("Enter credentials for the destination FMC.")
    credentials = utils.prompt_fmc_credentials()
    fmc_dst = utils.fmc_connect(*credentials)

    rules = load_autonatrules_from_json(INPUT_JSON_FILE)
    if not rules:
        logger.warning("No Auto NAT Rules found in '%s'. Nothing to do.", INPUT_JSON_FILE)
        fmc_dst.conn.session.close()
        return

    total = len(rules)
    migrated = 0
    failed = 0
    missing_objects: Set[Tuple[str, str]] = set()

    for index, rule in enumerate(rules, start=1):
        rule_desc = describe_rule(rule, index)
        logger.info("Processing %s (%d of %d).", rule_desc, index, total)

        rule_missing: List[Tuple[str, str]] = []
        payload = build_autonatrule_payload(fmc_dst, rule, rule_desc, rule_missing)

        if payload is None:
            failed += 1
            missing_objects.update(rule_missing)
            logger.error("[%s] Skipped: one or more referenced objects could not be resolved.", rule_desc)
            continue

        try:
            response = fmc_dst.policy.ftdnatpolicy.autonatrule.create(
                data=payload, container_uuid=DST_NAT_POLICY_UUID
            )
            status = getattr(response, "status_code", None)
            if status == 201:
                logger.info("[%s] Successfully created on destination FMC.", rule_desc)
                migrated += 1
            else:
                text = getattr(response, "text", "")
                logger.error("[%s] Failed to create Auto NAT Rule (HTTP %s): %s", rule_desc, status, text[:500])
                failed += 1
        except Exception:
            logger.exception("[%s] Error creating Auto NAT Rule on destination FMC.", rule_desc)
            failed += 1

    logger.info("=" * 60)
    logger.info("Migration Summary")
    logger.info("  Total rules processed      : %d", total)
    logger.info("  Successfully migrated      : %d", migrated)
    logger.info("  Failed                     : %d", failed)
    if missing_objects:
        logger.info("  Missing referenced objects : %d", len(missing_objects))
        for obj_type, obj_name in sorted(missing_objects):
            logger.info("    - %s '%s'", obj_type, obj_name)
    else:
        logger.info("  Missing referenced objects : none")
    logger.info("=" * 60)

    fmc_dst.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
