#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_acp_rules_using_two_fmc.py

Copies user assignments from matching Access Control Policy rules on a source
FMC to the equivalent rules on a target FMC. Only rules that carry a 'users'
field on the source are updated on the target.

Usage:
    Run this script directly. It will prompt for FMC-01 and FMC-02 credentials
    separately. Set SRC_ACP_UUID and DST_ACP_UUID to the correct policy UUIDs.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
import sys

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

SRC_ACP_UUID: str = "005056A1-C63D-0ed3-0000-008590051731"
DST_ACP_UUID: str = "005056A1-C63D-0ed3-0000-158913795943"


def main() -> None:
    """
    1. Connect to FMC-01 (source) and FMC-02 (target).
    2. Retrieve ACP rules from both FMCs.
    3. For each source rule with users, find the matching target rule and update it.
    """
    src_acp_uuid = SRC_ACP_UUID
    dst_acp_uuid = DST_ACP_UUID

    # Connect to FMC-01 (source)
    logger.info("Enter credentials for FMC-01 (source).")
    src_credentials = utils.prompt_fmc_credentials()  # prompt first time
    fmc_src = utils.fmc_connect(*src_credentials)

    # Connect to FMC-02 (target)
    logger.info("Enter credentials for FMC-02 (target).")
    dst_credentials = utils.prompt_fmc_credentials()  # prompt second time (can be same/different)
    fmc_dst = utils.fmc_connect(*dst_credentials)

    # 1) Read ACP rules from FMC-01 (source)
    logger.info("Retrieving ACP Rules from FMC-01")
    try:
        src_acp_rules = fmc_src.policy.accesspolicy.accessrule.get(container_uuid=src_acp_uuid)
    except Exception:
        logger.exception("Failed to retrieve ACP Rules from FMC-01")
        raise SystemExit(1)

    if not src_acp_rules:
        logger.warning("No ACP Rules found on source device")
        # Still close sessions cleanly
        fmc_src.conn.session.close()
        SystemExit(0)

    logger.info("Found %d ACP Rules on source device.", len(src_acp_rules))

    # 2) Read ACP rules from FMC-02 (target)
    logger.info("Retrieving ACP Rules from FMC-02")
    try:
        dst_acp_rules = fmc_dst.policy.accesspolicy.accessrule.get(container_uuid=dst_acp_uuid)
    except Exception:
        logger.exception("Failed to retrieve ACP Rules from FMC-02")
        raise SystemExit(1)

    if not src_acp_rules:
        logger.warning("No ACP Rules found on target device")
        # Still close sessions cleanly
        fmc_dst.conn.session.close()
        SystemExit(0)

    logger.info("Found %d ACP Rules on target device.", len(dst_acp_rules))
    updated, failed = 0, 0

    # 3) Process each ACP rule from source
    logger.info("Processing ACP Rules from source to target")
    number_of_src_rules = len(src_acp_rules)
    for index, src_rule in enumerate(src_acp_rules):
        logger.info("Processing ACP Rule: %d of %d", index + 1, number_of_src_rules)
        src_acp_rule_users = src_rule.get('users', None)
        if not src_acp_rule_users:
            logger.info("Skipping rule without users: %s", src_rule['name'])
            continue
        # Check if rule exists in target

        dst_acp_rule = next(
            (rule for rule in dst_acp_rules if rule["name"] == src_rule["name"]),
            None
        )
        if not dst_acp_rule:
            logger.info("No matching rule found in Target ACP: %s", src_rule['name'])
            continue
        # Update new rule in target
        logger.info("Found matching rule in target: %s", dst_acp_rule['name'])
        try:
            logger.info("Updating ACP Rule: %s", dst_acp_rule['name'])
            dst_acp_rule['users']= src_rule.get('users', None)
            # Update rule in target
            response = fmc_dst.policy.accesspolicy.accessrule.update(
                container_uuid=dst_acp_uuid,
                data=dst_acp_rule
            )

            # Some SDKs return a dict; others a Response-like object.
            status = getattr(response, "status_code", None)
            if status is not None and status == 200:
                logger.info("Successfully updated ACP Rule: %s", dst_acp_rule['name'])
                updated += 1
            else:
                logger.error("Failed to create ACP rule on target: %s", dst_acp_rule['name'])
                failed += 1
            logger.info("Successfully updated ACP rule on target: %s", dst_acp_rule['name'])
        except Exception as e:
            failed += 1
            logger.error("Failed to update ACP rule %s: %s", dst_acp_rule['name'], str(e))

    # Summary of updates
    logger.info("Update Summary: %d rules updated, %d failed", updated, failed)

    # Close sessions cleanly
    fmc_src.conn.session.close()
    fmc_dst.conn.session.close()

if __name__ == "__main__":
    main()


