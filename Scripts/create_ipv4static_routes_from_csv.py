# -*- coding: utf-8 -*-
"""
This script processes a CSV file containing a list of network objects and
creates corresponding static IPv4 routes for a Cisco Secure Firewall.

Each row in the CSV file should represent a static route. The script reads
each entry and attempts to create the corresponding object in the FTD.

Requirements:
- The input CSV file must be formatted correctly with the required fields.
- The UUID of the Cisco Secure Firewall appliance
- Proper authentication and API access to FMC must be configured.

Dependencies:
    - utils: Custom utility module containing FMC connection and credential handling functions.
    - FMC: Firepower Management Center Python client library.

Note:
- For devices in HA/Cluster, use the UUID of the Active/Control unit.

Author:
    Christian Méndez Murillo
"""

import logging
import utils
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

filename = "../Devices/devices.json"
ftd_uuid = "b155923e-db11-11ee-8794-be48d41fc879"

selectedNets = []
gateway_dict = {}

# Function to create a network object and return its UUID
def create_ipv4_staticroute(interface: str, selected_nets: list, obj_gateway: dict,) -> dict | None:

    payload = {
        "interfaceName": interface,
        "selectedNetworks": selected_nets,
          "gateway": {
            "object": obj_gateway
          },
        "metricValue": 1,
        "type": "IPv4StaticRoute",
        "isTunneled": False
    }

    try:
        response = fmc.device.devicerecord.routing.ipv4staticroute.create(container_uuid=ftd_uuid, data=payload)
        if response.status_code == 201:
            logging.info('Successfully created static route')
        else:
            logging.error('Error creating static route!!!')
            return None
    except Exception as e:
        logging.exception(f"Failed to create static route: {e}\n")
        return None

# Function to read a network object and return its UUID
def _get_object(object_name: str, object_type: str) -> Optional[dict]:
    """
    Retrieve an object from the FMC API and return its essential details.

    Args:
        object_name (str): The name of the object to retrieve.
        object_type (str): The type of the object to retrieve ('network' or 'host').

    Returns:
        Optional[dict]: A dictionary containing 'type', 'name', and 'id' of the object,
        or None if retrieval fails.
    """
    try:
        if object_type == 'network':
            response = fmc.object.network.get(name=object_name)
        elif object_type == 'host':
            response = fmc.object.host.get(name=object_name)
        else:
            logging.error("Unsupported object type: %s", object_type)
            return None

        if response and isinstance(response, dict):
            if 'error' not in response:
                logging.info("Successfully retrieved %s object: %s", object_type, object_name)
                return {
                    'type': response.get('type'),
                    'name': response.get('name'),
                    'id': response.get('id')
                }
            else:
                logging.error(
                    "Error retrieving %s object '%s': %s",
                    object_type,
                    object_name,
                    response.get('error')
                )
        else:
            logging.error("Empty or invalid response for %s object '%s'", object_type, object_name)

    except Exception as e:
        logging.exception("Failed to retrieve %s object '%s'", object_type, object_name)

    return None

def get_network_object(object_name: str) -> Optional[dict]:
    """
    Retrieve a network object from the FMC API.

    Args:
        object_name (str): The name of the network object.

    Returns:
        Optional[dict]: A dictionary containing object details or None if retrieval fails.
    """
    return _get_object(object_name, "network")

def get_host_object(object_name: str) -> Optional[dict]:
    """
    Retrieve a host object from the FMC API.

    Args:
        object_name (str): The name of the host object.

    Returns:
        Optional[dict]: A dictionary containing object details or None if retrieval fails.
    """
    return _get_object(object_name, "host")

if __name__ == '__main__':
    credentials = utils.prompt_fmc_credentials()
    fmc = utils.fmc_connect(*credentials)

    # Open the CSV file and read network objects
    csv_reader = utils.read_csv_file(filename)

    if csv_reader is None:
        logging.error("Failed to read the CSV file. Exiting.")
        exit(1)

    # Loop through each row in the CSV to create the static routes
    for row in csv_reader:
        # Extract fields from the CSV
        nets = []
        interf = row['interfaceName']
        networks = row['selectedNetworks']
        gateway = row['gateway']  # Network Object

        # Retrieve network/host objects for each selected network
        for net in networks.split(";"):
            net_info = get_network_object(net) or get_host_object(net)
            if net_info:
                nets.append(net_info)
            else:
                logging.error(f'Network/Host object not found: {net}')
                continue

        gateway_obj = get_host_object(gateway)
        if not gateway_obj:
            logging.error(f'Gateway Network object not found: {gateway_obj}')
            continue

        # Create the network object in FMC and retrieve the object info
        logging.info(f'Creating static route: {interf} {nets} {gateway}')
        static_route = create_ipv4_staticroute(interf, nets, gateway_obj)

    # Close the FMC session
    fmc.conn.session.close()