# fireREST FMC Scripts

A collection of Python scripts for automating Cisco Firepower Management Center (FMC) configuration and administration via the [fireREST](https://github.com/kaisero/fireREST) library.

---

## What is fireREST?

[fireREST](https://github.com/kaisero/fireREST) is a Python client library that wraps the Cisco FMC REST API into a clean, hierarchical object model. Instead of building raw HTTP requests, you navigate the API as Python attributes:

```python
from fireREST import FMC

fmc = FMC(hostname="192.168.1.1", username="admin", password="Admin123")

# GET all managed devices
devices = fmc.device.devicerecord.get()

# GET IPv4 static routes on a specific FTD
routes = fmc.device.devicerecord.routing.ipv4staticroute.get(container_uuid="<ftd-uuid>")

# POST a new host object
fmc.object.host.create(data={"name": "Server-01", "value": "10.0.0.10", "type": "Host"})
```

The library handles authentication (token refresh), pagination, and SSL by default.

---

## Repository Structure

```
fireREST_FMC_Scripts/
├── utils.py                  # Shared helpers: connection, CSV/JSON I/O
├── logging_utils.py          # Logging configuration
│
├── FMC/                      # Single-purpose query/create scripts
│   ├── Chassis/              # Chassis information
│   ├── Deployment/           # Deployable devices and deployment requests
│   ├── DeviceHAPairs/        # FTD HA pair management
│   ├── Devices/              # Device records, interfaces, routing, virtual routers
│   └── Object/               # Network objects, security zones, network groups
│
└── Scripts/                  # Bulk/automation scripts
    ├── create_ipv4static_routes_from_csv.py
    ├── create_ipv4static_routes_from_csv_and_json.py
    ├── create_network_objects_from_csv.py
    ├── create_subinterfaces_from_csv.py
    ├── delete_ipv4_static_routes_from_csv.py
    ├── delete_unused_objets.py
    ├── fmc_dynamic_objects.py
    ├── migrate_ftd_ipv4_static_routes.py
    ├── migrate_ftd_ipv4_static_routes_using_two_fmc.py
    ├── migrate_ftd_ipv4_static_routes_using_two_fmc_v0.2.py
    ├── update_acp_rules_using_two_fmc.py
    └── backup_objects_object_management.py
```

---

## Prerequisites

- Python 3.14+
- Access to a Cisco FMC instance with REST API enabled
- An FMC user account with API permissions

---

## Setup

```bash
# Clone the repository
git clone https://github.com/your-username/fireREST_FMC_Scripts.git
cd fireREST_FMC_Scripts

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Unix/macOS

# Install the project and its dependencies
pip install -e .

# Install fireREST
pip install fireREST
```

---

## Usage

### Connecting to FMC

All scripts use the shared `utils.py` helpers to connect. Credentials are always prompted at runtime — never hardcoded.

```python
import utils

# Interactive prompt (hostname, username, password, domain)
credentials = utils.prompt_fmc_credentials()
fmc = utils.fmc_connect(*credentials)
```

Alternatively, pass credentials directly:

```python
from utils import fmc_connect

fmc = fmc_connect(
    hostname="192.168.1.1",
    username="api_user",
    password="your_password",
    domain="Global"           # defaults to "Global"
)
```

### Running a script

Each script under `FMC/` or `Scripts/` is self-contained and runs independently:

```bash
# Example: list all managed devices
python FMC/Devices/get_devices.py

# Example: export dynamic objects to JSON
python Scripts/fmc_dynamic_objects.py

# Example: create IPv4 static routes from a CSV file
python Scripts/create_ipv4static_routes_from_csv.py
```

---

## Script Reference

### FMC/Devices

| Script | Description |
|--------|-------------|
| `get_devices.py` | List all FTD devices managed by the FMC |
| `get_device_by_name.py` | Retrieve a single device by name |
| `get_physical_interfaces.py` | List physical interfaces on an FTD |
| `get_subinterfaces.py` | List sub-interfaces on an FTD |
| `get_ipv4_static_route.py` | Retrieve IPv4 static routes from an FTD |
| `get_ipv4_static_routes_to_csv.py` | Export IPv4 static routes to a CSV file |
| `delete_ipv4_static_route.py` | Delete a specific IPv4 static route |
| `get_ospfinterface_global.py` | Get OSPF interface settings (global VRF) |
| `get_ospfinterface_vrf.py` | Get OSPF interface settings (custom VRF) |
| `get_virtualrouter.py` | List virtual routers on an FTD |
| `create_virtualrouter.py` | Create a virtual router on an FTD |

### FMC/Object

| Script | Description |
|--------|-------------|
| `get_objects.py` | List all network objects |
| `post_objects.py` | Create a new network object |
| `get_networkgroups.py` | List all network groups |
| `get_networkgroups_byid.py` | Retrieve a network group by UUID |
| `get_securityzones.py` | List all security zones |
| `get_securityzone_byid.py` | Retrieve a security zone by UUID |

### FMC/Deployment

| Script | Description |
|--------|-------------|
| `get_deployabledevices.py` | List devices with pending changes |
| `get_deployabledevices_id.py` | Get details for a specific deployable device |
| `get_deployabledevices_id_pendingchanges.py` | Show pending changes for a device |
| `post_deploymentrequests.py` | Trigger a policy deployment |

### FMC/DeviceHAPairs

| Script | Description |
|--------|-------------|
| `get_ftddevicehapairs.py` | List all FTD HA pairs |
| `get_ftddevicehapairs_id.py` | Retrieve a specific HA pair by UUID |
| `create_ftddevicehapairs.py` | Create a new FTD HA pair |

### FMC/Chassis

| Script | Description |
|--------|-------------|
| `get_chassis.py` | Retrieve chassis information |

### Scripts/ (Bulk Operations)

| Script | Description |
|--------|-------------|
| `create_ipv4static_routes_from_csv.py` | Bulk-create IPv4 static routes from a CSV |
| `create_ipv4static_routes_from_csv_and_json.py` | Create routes using CSV + JSON source data |
| `create_network_objects_from_csv.py` | Bulk-create network host/network objects from a CSV |
| `create_subinterfaces_from_csv.py` | Bulk-create sub-interfaces from a CSV |
| `delete_ipv4_static_routes_from_csv.py` | Delete static routes listed in a CSV |
| `delete_unused_objets.py` | Identify and remove unused network objects |
| `fmc_dynamic_objects.py` | Export all dynamic objects and their IP mappings to JSON |
| `migrate_ftd_ipv4_static_routes.py` | Migrate static routes between FTDs on the same FMC |
| `migrate_ftd_ipv4_static_routes_using_two_fmc.py` | Migrate static routes across two separate FMC instances, auto-replicating referenced objects |
| `update_acp_rules_using_two_fmc.py` | Replicate Access Control Policy rules between two FMC instances |
| `backup_objects_object_management.py` | Back up all object management entries to JSON |

---

## CSV Format Examples

### IPv4 Static Routes (`ftd_ipv4_static_routes.csv`)

```
interfaceName,selectedNetworks,gateway
outside,10.0.1.0_Network;10.0.2.0_Network,GW-ISP-Host
inside,192.168.10.0_Network,GW-Internal-Host
```

- `selectedNetworks` — semicolon-separated list of FMC object names (Host or Network type)
- `gateway` — FMC Host object name used as the next hop

---

## Shared Utilities (`utils.py`)

| Function | Description |
|----------|-------------|
| `fmc_connect(hostname, username, password, domain)` | Authenticate and return an FMC session |
| `prompt_fmc_credentials()` | Interactive credential prompt (uses `getpass` for password) |
| `save_json_to_file(filename, data)` | Write a dict to a JSON file |
| `load_routes_from_json(filepath)` | Load a route backup JSON, keyed by UUID |
| `read_csv_file(file_path)` | Read a CSV and return rows as a list of lists |
| `load_uuids_from_csv(filepath)` | Read a single-column CSV of UUIDs |
| `write_csv(path, rows, fieldnames)` | Write a list of dicts to a CSV with headers |

---

## Security Notes

- **Never hardcode credentials.** All scripts prompt interactively or read from environment variables.
- SSL certificate verification is disabled (`verify_cert=False`) in lab environments. Set it to `True` in production with a valid FMC certificate.
- For HA/Cluster devices, always target the **Active/Control** unit UUID for write operations.

---

## Requirements

- [fireREST](https://github.com/kaisero/fireREST) — `pip install fireREST`
- Python 3.14+

---

## Author

Christian Méndez Murillo
