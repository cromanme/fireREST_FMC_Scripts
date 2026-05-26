#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fmc_inventory.py
----------------
Connects to a Cisco FMC and produces a resource inventory for:
  - Devices        > devicerecords
  - Device HA Pairs> ftddevicehapairs
  - Device Groups  > devicegrouprecords
  - Device Clusters> ftddeviceclusters

Results are printed as ASCII tables and saved to a timestamped text file.

Usage:
    python fmc_inventory.py

Dependencies:
    - utils: shared FMC connection and credential helpers (project root)
    - fireREST: pip install fireREST

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

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

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


# ---------------------------------------------------------------------------
# ASCII table renderer
# ---------------------------------------------------------------------------

def _ascii_table(headers: list[str], rows: list[list[str]], title: str = "") -> str:
    """Return a plain-text ASCII table."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    header_row = "|" + "|".join(
        f" {h:<{w}} " for h, w in zip(headers, col_widths)
    ) + "|"

    lines: list[str] = []

    if title:
        table_width = len(sep)
        lines.append("=" * table_width)
        padding = (table_width - len(title) - 2) // 2
        lines.append(" " * padding + title)
        lines.append("=" * table_width)

    lines.append(sep)
    lines.append(header_row)
    lines.append(sep.replace("-", "="))

    if rows:
        for row in rows:
            data_row = "|" + "|".join(
                f" {str(cell):<{w}} " for cell, w in zip(row, col_widths)
            ) + "|"
            lines.append(data_row)
    else:
        empty_msg = "  (no records found)"
        lines.append(empty_msg)

    lines.append(sep)
    lines.append(f"  Records: {len(rows)}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inventory collectors
# ---------------------------------------------------------------------------

def _normalize(response) -> list[dict]:
    """Normalise a fireREST response to a plain list of dicts."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return response.get("items", [])
    return []


def collect_devices(fmc) -> tuple[str, list[dict]]:
    """Retrieve device records and return (table_text, raw_items)."""
    logger.info("Collecting device records …")
    try:
        raw = _normalize(fmc.device.devicerecord.get())
    except Exception:
        logger.exception("Failed to retrieve device records.")
        raw = []

    headers = ["#", "Name", "UUID", "Model", "SW Version", "Health Status"]
    rows = []
    for idx, item in enumerate(raw, start=1):
        rows.append([
            str(idx),
            item.get("name", ""),
            item.get("id", ""),
            item.get("model", ""),
            item.get("sw_version", item.get("swVersion", "")),
            item.get("healthStatus", ""),
        ])

    table = _ascii_table(headers, rows, title="Devices > Device Records")
    return table, raw


def collect_ha_pairs(fmc) -> tuple[str, list[dict]]:
    """Retrieve FTD HA pairs and return (table_text, raw_items)."""
    logger.info("Collecting FTD HA pairs …")
    try:
        raw = _normalize(fmc.devicehapair.ftdhapair.get())
    except Exception:
        logger.exception("Failed to retrieve FTD HA pairs.")
        raw = []

    headers = ["#", "Name", "UUID", "Primary Device", "Secondary Device", "Status"]
    rows = []
    for idx, item in enumerate(raw, start=1):
        primary   = item.get("primary",   {})
        secondary = item.get("secondary", {})
        rows.append([
            str(idx),
            item.get("name", ""),
            item.get("id", ""),
            primary.get("name", primary.get("id", "")),
            secondary.get("name", secondary.get("id", "")),
            item.get("haStatus", item.get("status", "")),
        ])

    table = _ascii_table(headers, rows, title="Device HA Pairs > FTD HA Pairs")
    return table, raw


def collect_device_groups(fmc) -> tuple[str, list[dict]]:
    """Retrieve device group records and return (table_text, raw_items)."""
    logger.info("Collecting device group records …")
    try:
        raw = _normalize(fmc.devicegroup.devicegrouprecord.get())
    except Exception:
        logger.exception("Failed to retrieve device group records.")
        raw = []

    headers = ["#", "Name", "UUID", "Member Count"]
    rows = []
    for idx, item in enumerate(raw, start=1):
        members = item.get("members", [])
        rows.append([
            str(idx),
            item.get("name", ""),
            item.get("id", ""),
            str(len(members)),
        ])

    table = _ascii_table(headers, rows, title="Device Groups > Device Group Records")
    return table, raw


def collect_clusters(fmc) -> tuple[str, list[dict]]:
    """Retrieve FTD device clusters and return (table_text, raw_items)."""
    logger.info("Collecting FTD device clusters …")
    try:
        raw = _normalize(fmc.devicecluster.ftddevicecluster.get())
    except Exception:
        logger.exception("Failed to retrieve FTD device clusters.")
        raw = []

    headers = ["#", "Name", "UUID", "Control Node", "Data Node Count"]
    rows = []
    for idx, item in enumerate(raw, start=1):
        control_node = item.get("controlDevice", item.get("masterDevice", {}))
        data_nodes   = item.get("dataDevices",   item.get("slaveDevices", []))
        rows.append([
            str(idx),
            item.get("name", ""),
            item.get("id", ""),
            control_node.get("name", control_node.get("id", "")) if isinstance(control_node, dict) else str(control_node),
            str(len(data_nodes)),
        ])

    table = _ascii_table(headers, rows, title="Device Clusters > FTD Device Clusters")
    return table, raw


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _build_report(sections: list[str], fmc_ip: str) -> str:
    """Wrap all table sections in a report header/footer."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    border = "=" * 72
    header = "\n".join([
        border,
        "  Cisco FMC Resource Inventory",
        f"  FMC Host : {fmc_ip}",
        f"  Generated: {ts}",
        border,
        "",
    ])
    return header + "\n".join(sections)


def save_report(content: str, fmc_ip: str) -> Path:
    """Write *content* to a timestamped .txt file and return its Path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ip  = fmc_ip.replace(".", "_").replace(":", "_")
    filename = f"fmc_inventory_{safe_ip}_{ts}.txt"
    filepath = OUTPUT_DIR / filename

    with filepath.open("w", encoding="utf-8") as fh:
        fh.write(content)

    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Credentials
    credentials = utils.prompt_fmc_credentials()
    fmc_ip = credentials[0]

    # 2. Connect
    fmc = utils.fmc_connect(*credentials)

    # 3. Collect each resource category
    sections: list[str] = []
    for collector in (collect_devices, collect_ha_pairs, collect_device_groups, collect_clusters):
        table, _ = collector(fmc)
        sections.append(table)

    # 4. Build & print report
    report = _build_report(sections, fmc_ip)
    print("\n" + report)

    # 5. Save to file
    output_path = save_report(report, fmc_ip)
    logger.info("Inventory saved to: %s", output_path.resolve())
    print(f"[+] Report saved to: {output_path.resolve()}")

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
