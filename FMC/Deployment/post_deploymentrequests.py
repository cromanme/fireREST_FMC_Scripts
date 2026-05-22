#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
post_deploymentrequests.py

Connects to a Cisco FMC, resolves an FTD device by hostname, and triggers
a deployment of pending changes to that device.

Usage:
    Run this script directly. It will prompt for FMC credentials.
    Set FTD_HOSTNAME to the name of the target device.

    Note: DEPLOY_VERSION must match the version token returned by the
    deployabledevices endpoint. Update it before each deployment run.

Dependencies:
    - utils: shared FMC connection and I/O helpers.
    - fireREST: Firepower Management Center Python client library.

Author:
    Christian Méndez Murillo
"""

from __future__ import annotations

import logging
from typing import Dict

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

FTD_HOSTNAME: str   = "266rpvPUEfpr4115-01"
# Version token from the deployabledevices endpoint — update before each run.
DEPLOY_VERSION: str = "1715277438719"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_deployment_payload(ftd_uuid: str, version: str) -> Dict:
    """
    Build the deployment request payload.

    Args:
        ftd_uuid (str): UUID of the FTD device to deploy.
        version (str): Version token from the deployabledevices endpoint.

    Returns:
        Dict: Payload ready to POST to the FMC deployment API.
    """
    return {
        "type":          "DeploymentRequest",
        "version":       version,
        "forceDeploy":   False,
        "ignoreWarning": True,
        "deviceList":    [ftd_uuid],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Trigger a deployment of pending changes for the target FTD device."""
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    try:
        ftd_info = fmc.device.devicerecord.get(name=FTD_HOSTNAME)
        ftd_uuid = ftd_info["id"]
    except Exception:
        logger.exception("Failed to resolve device UUID for '%s'.", FTD_HOSTNAME)
        raise SystemExit(1)

    payload = build_deployment_payload(ftd_uuid, DEPLOY_VERSION)
    logger.info("Triggering deployment for device '%s' (%s).", FTD_HOSTNAME, ftd_uuid)

    try:
        fmc.deployment.deploymentrequest.create(data=payload)
        logger.info("Deployment request submitted successfully.")
    except Exception:
        logger.exception("Failed to submit deployment request for '%s'.", FTD_HOSTNAME)
        raise SystemExit(1)

    fmc.conn.session.close()
    logger.info("FMC session closed.")


if __name__ == "__main__":
    main()
