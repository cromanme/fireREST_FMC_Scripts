#!/usr/bin/env python3
"""
fmc_dynamic_objects.py
----------------------
Connects to a Cisco FMC instance via fireREST, retrieves all Dynamic Objects
and their IP mappings, then saves the results to a timestamped JSON file.

Requirements:
    pip install fireREST
"""

import json
import getpass
import sys
from datetime import datetime
from pathlib import Path

try:
    from fireREST import FMC
    from fireREST.exceptions import FireRESTApiException, FireRESTAuthException
except ImportError:
    print(
        "[ERROR] fireREST is not installed.\n"
        "        Install it with:  pip install fireREST"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def prompt_credentials() -> tuple[str, str, str]:
    """Prompt the operator for FMC IP and credentials and return them."""
    print("=" * 55)
    print("  Cisco FMC – Dynamic Object Exporter")
    print("=" * 55)
    fmc_ip   = input("FMC IP / Hostname : ").strip()
    username = input("Username          : ").strip()
    password = getpass.getpass("Password          : ")

    if not fmc_ip or not username or not password:
        print("[ERROR] FMC IP, username and password are all required.")
        sys.exit(1)

    return fmc_ip, username, password


# ---------------------------------------------------------------------------
# FMC helpers
# ---------------------------------------------------------------------------

def connect(fmc_ip: str, username: str, password: str) -> FMC:
    """Authenticate to FMC and return an FMC session object."""
    print(f"\n[*] Connecting to FMC at {fmc_ip} …")
    try:
        fmc = FMC(
            hostname=fmc_ip,
            username=username,
            password=password,
            verify_cert=False,          # set True in production with a valid cert
        )
        print("[+] Authentication successful.")
        return fmc
    except FireRESTAuthException as exc:
        print(f"[ERROR] Authentication failed: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] Could not connect to FMC: {exc}")
        sys.exit(1)


def get_dynamic_objects(fmc: FMC) -> list[dict]:
    """Return a list of all Dynamic Object dicts from FMC."""
    print("\n[*] Retrieving Dynamic Objects …")
    try:
        response = fmc.object.dynamicobject.get()

        # fireREST may return a list directly or a paged dict with 'items'
        if isinstance(response, list):
            objects = response
        elif isinstance(response, dict):
            objects = response.get("items", [])
        else:
            objects = []

        print(f"[+] Found {len(objects)} Dynamic Object(s).")
        return objects

    except FireRESTApiException as exc:
        print(f"[ERROR] Failed to retrieve Dynamic Objects: {exc}")
        sys.exit(1)


def get_mappings(fmc: FMC, obj_id: str, obj_name: str) -> list[str]:
    """Return the IP mappings for a single Dynamic Object."""
    try:
        response = fmc.object.dynamicobjectmapping.get(container_uuid=obj_id)

        if isinstance(response, list):
            mappings = response
        elif isinstance(response, dict):
            mappings = response.get("items", [])
        else:
            mappings = []

        # Each mapping item typically has an 'address' field
        addresses = [
            m.get("address") or m.get("value") or str(m)
            for m in mappings
        ]
        return addresses

    except FireRESTApiException as exc:
        # A 404 just means no mappings exist yet; anything else is unexpected
        print(f"  [WARN] Could not retrieve mappings for '{obj_name}': {exc}")
        return []


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def build_timestamp() -> str:
    """Return a filesystem-safe timestamp string."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_results(data: list[dict], output_dir: str = ".") -> Path:
    """Serialise *data* to a timestamped JSON file and return the Path."""
    timestamp = build_timestamp()
    filename  = f"dynamic_objects_{timestamp}.json"
    filepath  = Path(output_dir) / filename

    filepath.parent.mkdir(parents=True, exist_ok=True)

    with filepath.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Collect credentials
    fmc_ip, username, password = prompt_credentials()

    # 2. Authenticate
    fmc = connect(fmc_ip, username, password)

    # 3. Retrieve all Dynamic Objects
    dynamic_objects = get_dynamic_objects(fmc)

    if not dynamic_objects:
        print("[!] No Dynamic Objects found. Exiting.")
        sys.exit(0)

    # 4. Enrich each object with its IP mappings
    print("\n[*] Retrieving mappings for each Dynamic Object …")
    results: list[dict] = []

    for idx, obj in enumerate(dynamic_objects, start=1):
        obj_id   = obj.get("id",   "")
        obj_name = obj.get("name", f"object_{idx}")
        obj_type = obj.get("objectType", "")

        print(f"  [{idx}/{len(dynamic_objects)}] {obj_name} ({obj_type})")

        mappings = get_mappings(fmc, obj_id, obj_name)

        results.append(
            {
                "id":          obj_id,
                "name":        obj_name,
                "objectType":  obj_type,
                "description": obj.get("description", ""),
                "mappings":    mappings,
                "mappingCount": len(mappings),
            }
        )

    # 5. Save to timestamped file
    print("\n[*] Saving results …")
    output_path = save_results(results)
    print(f"[+] Results saved to: {output_path.resolve()}")
    print(f"    Total objects exported : {len(results)}")
    total_mappings = sum(r["mappingCount"] for r in results)
    print(f"    Total mappings exported: {total_mappings}")


if __name__ == "__main__":
    main()
