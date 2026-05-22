# -*- coding: utf-8 -*-
"""
utils.py

Shared helpers for all FMC scripts: connection, credential prompting,
CSV/JSON I/O.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from typing import Dict, List, Optional

from fireREST import FMC

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FMC connection
# ---------------------------------------------------------------------------

def fmc_connect(hostname: str, username: str, password: str, domain: str = "Global") -> FMC:
    """
    Authenticate to FMC and return an FMC session object.

    Args:
        hostname (str): Hostname or IP address of the FMC.
        username (str): FMC API username.
        password (str): FMC API password.
        domain (str): FMC domain. Defaults to "Global".

    Returns:
        FMC: Authenticated FMC client instance.

    Raises:
        SystemExit: If authentication or connection fails.
    """
    try:
        fmc = FMC(hostname=hostname, username=username, password=password, domain=domain)
        logger.info("Connected to FMC successfully.")
    except Exception as e:
        logger.error("Failed to connect to FMC: %s", e)
        raise SystemExit(1)
    return fmc


def prompt_fmc_credentials() -> tuple[str, str, str, str]:
    """
    Prompt the operator for FMC connection details and return them.

    Returns:
        tuple: (hostname, username, password, domain)
    """
    import getpass
    hostname = input("FMC hostname or IP address : ").strip()
    username = input("Username                   : ").strip()
    password = getpass.getpass("Password                   : ")
    domain   = input("Domain (default 'Global')  : ").strip() or "Global"
    return hostname, username, password, domain


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def save_json_to_file(filename: str, data: dict) -> None:
    """
    Serialize *data* as JSON and write it to *filename*.

    Args:
        filename (str): Destination file path.
        data (dict): Data to serialize.

    Raises:
        OSError: If the file cannot be written.
        TypeError: If *data* is not JSON-serializable.
    """
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info("Data saved to '%s'.", filename)
    except (OSError, TypeError) as e:
        logger.error("Failed to save data to '%s': %s", filename, e)
        raise


def load_routes_from_json(filepath: str) -> Dict[str, dict]:
    """
    Load a JSON backup produced by get_ipv4_static_route.py and return a
    UUID-keyed dict of route definitions.

    Args:
        filepath (str): Path to the JSON backup file.

    Returns:
        Dict[str, dict]: Route definitions keyed by UUID.

    Raises:
        SystemExit: If the file is missing, unreadable, or not valid JSON.
    """
    try:
        with open(filepath, mode="r", encoding="utf-8") as f:
            routes_list: List[dict] = json.load(f)

        routes_by_uuid: Dict[str, dict] = {
            route["id"]: route
            for route in routes_list
            if "id" in route
        }
        logger.info("Loaded %d route(s) from '%s'.", len(routes_by_uuid), filepath)
        return routes_by_uuid

    except FileNotFoundError:
        logger.error("JSON backup file not found: '%s'.", filepath)
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON file '%s': %s", filepath, e)
        raise SystemExit(1)
    except Exception as e:
        logger.error("Unexpected error reading JSON file '%s': %s", filepath, e)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def read_csv_file(file_path: str) -> Optional[List[List[str]]]:
    """
    Read a CSV file and return its rows as a list of string lists.

    Args:
        file_path (str): Path to the CSV file.

    Returns:
        Optional[List[List[str]]]: Rows, or None if an error occurs.
    """
    if not os.path.exists(file_path):
        logger.error("File not found: '%s'.", file_path)
        return None
    try:
        with open(file_path, mode="r", newline="", encoding="utf-8") as f:
            return list(csv.reader(f))
    except Exception as e:
        logger.error("Error reading '%s': %s", file_path, e)
        return None


def load_uuids_from_csv(filepath: str) -> List[str]:
    """
    Read a single-column CSV (no header) and return a list of UUID strings.

    Args:
        filepath (str): Path to the CSV file.

    Returns:
        List[str]: UUIDs found in the file.

    Raises:
        SystemExit: If the file is not found or cannot be read.
    """
    uuids: List[str] = []
    try:
        with open(filepath, mode="r", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and row[0].strip():
                    uuids.append(row[0].strip())
        logger.info("Loaded %d UUID(s) from '%s'.", len(uuids), filepath)
    except FileNotFoundError:
        logger.error("CSV file not found: '%s'.", filepath)
        raise SystemExit(1)
    except Exception as e:
        logger.error("Failed to read CSV file '%s': %s", filepath, e)
        raise SystemExit(1)
    return uuids


def write_csv(path: str, rows: List[dict], fieldnames: List[str]) -> None:
    """
    Write *rows* to a UTF-8-with-BOM CSV file at *path*.

    Creates missing parent directories automatically. Overwrites any
    existing file at the same path.

    Args:
        path (str): Destination file path (including filename).
        rows (List[dict]): Rows to write; each key must be in *fieldnames*.
        fieldnames (List[str]): Ordered column headers.
    """
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logger.info("CSV written: %s", path)
    except PermissionError:
        logger.error("Permission denied writing file: %s", path)
    except FileNotFoundError:
        logger.error("Invalid path or missing directory: %s", path)
    except OSError as e:
        logger.error("OS error writing CSV '%s': %s", path, e)
    except Exception as e:
        logger.error("Unexpected error writing CSV '%s': %s", path, e)
