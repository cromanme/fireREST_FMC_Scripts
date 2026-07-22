#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ftd_interfaces_inventory.py

Connects to a Cisco FMC and produces an interface inventory for a single FTD:
  - EtherChannel Interfaces
  - Physical Interfaces
  - Sub-Interfaces

Results are printed as ASCII tables (Name, UUID) and saved to a timestamped
text file, mirroring the report style of fmc_inventory.py.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_UUID to the UUID of the target FTD device.

Dependencies:
    - utils: shared FMC connection and credential helpers (project root)
    - fireREST: pip install fireREST

Note:
    For devices in HA/Cluster, use the UUID of the Active/Control unit.

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

FTD_UUID: str = "756040da-4b12-11f1-86c8-9612df00d0df"


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
        lines.append("  (no records found)")

    lines.append(sep)
    lines.append(f"  Records: {len(rows)}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interface collectors
# ---------------------------------------------------------------------------

def _normalize(response) -> list[dict]:
    """Normalise a fireREST response to a plain list of dicts."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return response.get("items", [response])
    return []


def _name_uuid_table(raw: list[dict], title: str) -> str:
    """Build a Name/UUID ASCII table from a list of interface dicts."""
    headers = ["#", "Name", "UUID"]
    rows = [
        [str(idx), item.get("name", ""), item.get("id", "")]
        for idx, item in enumerate(raw, start=1)
    ]
    return _ascii_table(headers, rows, title=title)


def collect_etherchannel_interfaces(fmc, ftd_uuid: str) -> tuple[str, list[dict]]:
    """Retrieve EtherChannel interfaces for *ftd_uuid* and return (table_text, raw_items)."""
    logger.info("Collecting EtherChannel interfaces …")
    try:
        raw = _normalize(
            fmc.device.devicerecord.etherchannelinterface.get(container_uuid=ftd_uuid)
        )
    except Exception:
        logger.exception("Failed to retrieve EtherChannel interfaces.")
        raw = []
    logger.info("Found %d EtherChannel interface(s).", len(raw))
    return _name_uuid_table(raw, title="EtherChannel Interfaces"), raw


def collect_physical_interfaces(fmc, ftd_uuid: str) -> tuple[str, list[dict]]:
    """Retrieve physical interfaces for *ftd_uuid* and return (table_text, raw_items)."""
    logger.info("Collecting physical interfaces …")
    try:
        raw = _normalize(
            fmc.device.devicerecord.physicalinterface.get(container_uuid=ftd_uuid)
        )
    except Exception:
        logger.exception("Failed to retrieve physical interfaces.")
        raw = []
    logger.info("Found %d physical interface(s).", len(raw))
    return _name_uuid_table(raw, title="Physical Interfaces"), raw


def collect_subinterfaces(fmc, ftd_uuid: str) -> tuple[str, list[dict]]:
    """Retrieve sub-interfaces for *ftd_uuid* and return (table_text, raw_items)."""
    logger.info("Collecting sub-interfaces …")
    try:
        raw = _normalize(
            fmc.device.devicerecord.subinterface.get(container_uuid=ftd_uuid)
        )
    except Exception:
        logger.exception("Failed to retrieve sub-interfaces.")
        raw = []
    logger.info("Found %d sub-interface(s).", len(raw))
    return _name_uuid_table(raw, title="Sub-Interfaces"), raw


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _build_report(sections: list[str], ftd_uuid: str) -> str:
    """Wrap all table sections in a report header/footer."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    border = "=" * 72
    header = "\n".join([
        border,
        "  FTD Interface Inventory",
        f"  FTD UUID   : {ftd_uuid}",
        f"  Generated  : {ts}",
        border,
        "",
    ])
    return header + "\n".join(sections)


def save_report(content: str, ftd_uuid: str) -> Path:
    """Write *content* to a timestamped .txt file and return its Path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ftd_interfaces_inventory_{ftd_uuid}_{ts}.txt"
    filepath = OUTPUT_DIR / filename

    with filepath.open("w", encoding="utf-8") as fh:
        fh.write(content)

    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Connect to FMC and produce an EtherChannel/Physical/Sub-Interface
    inventory for FTD_UUID, printed as ASCII tables and saved to a file.
    """
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    sections: list[str] = []
    for collector in (
        collect_etherchannel_interfaces,
        collect_physical_interfaces,
        collect_subinterfaces,
    ):
        table, _ = collector(fmc, FTD_UUID)
        sections.append(table)

    report = _build_report(sections, FTD_UUID)
    print("\n" + report)

    output_path = save_report(report, FTD_UUID)
    logger.info("Inventory saved to: %s", output_path.resolve())
    print(f"[+] Report saved to: {output_path.resolve()}")

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
