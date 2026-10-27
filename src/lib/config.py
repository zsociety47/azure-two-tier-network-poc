"""Names, addresses, and tags for the two-tier proof of concept.

Every Azure resource this project creates is listed here so deploy, verify,
and teardown stay in agreement. If you are not zeon, change RESOURCE_GROUP
and TAGS["owner"] before you deploy. The resource group name must be yours.
"""

from dataclasses import dataclass


LOCATION = "eastus"
RESOURCE_GROUP = "rg-twotier-poc-zeon01"
VNET_NAME = "vnet-twotier-poc"
VNET_PREFIX = "10.0.0.0/16"

WEB_SUBNET = "snet-web"
WEB_PREFIX = "10.0.1.0/24"
DB_SUBNET = "snet-db"
DB_PREFIX = "10.0.2.0/24"
TEST_SUBNET = "snet-test"
TEST_PREFIX = "10.0.3.0/24"

NSG_WEB = "nsg-web"
NSG_DB = "nsg-db"
NSG_TEST = "nsg-test"

VM_WEB = "vm-web-01"
VM_DB = "vm-db-01"
VM_TEST = "vm-test-01"
WEB_PRIVATE_IP = "10.0.1.4"
DB_PRIVATE_IP = "10.0.2.4"
TEST_PRIVATE_IP = "10.0.3.4"

PIP_WEB = "pip-web-01"
PIP_NAT = "pip-nat-01"
NAT_GATEWAY = "nat-twotier-poc"

NIC_WEB = "nic-web-01"
NIC_DB = "nic-db-01"
NIC_TEST = "nic-test-01"

ADMIN_USER = "azureuser"
VM_SIZE = "Standard_F1als_v7"
IMAGE = {
    "publisher": "Canonical",
    "offer": "ubuntu-24_04-lts",
    "sku": "server",
    "version": "latest",
}

DB_PORT = 5432
WEB_PORT = 80
PAGE_MARKER = "database-connected"

TAGS = {
    "project": "azure-two-tier-network-poc",
    "environment": "poc",
    "managed-by": "python-sdk",
    "owner": "zeon",
}


@dataclass(frozen=True)
class SubnetSpec:
    name: str
    prefix: str
    nsg: str
    attach_nat: bool


@dataclass(frozen=True)
class VmSpec:
    name: str
    nic: str
    subnet: str
    private_ip: str
    public_ip: str | None


SUBNETS = (
    SubnetSpec(WEB_SUBNET, WEB_PREFIX, NSG_WEB, attach_nat=False),
    SubnetSpec(DB_SUBNET, DB_PREFIX, NSG_DB, attach_nat=True),
    SubnetSpec(TEST_SUBNET, TEST_PREFIX, NSG_TEST, attach_nat=False),
)

VMS = (
    VmSpec(VM_WEB, NIC_WEB, WEB_SUBNET, WEB_PRIVATE_IP, PIP_WEB),
    VmSpec(VM_DB, NIC_DB, DB_SUBNET, DB_PRIVATE_IP, None),
    VmSpec(VM_TEST, NIC_TEST, TEST_SUBNET, TEST_PRIVATE_IP, None),
)
