"""Create the two-tier network proof of concept.

Run from the repository root:

    python -m src.deploy --plan
    python -m src.deploy
"""

import argparse

from azure.core.exceptions import ResourceNotFoundError
from azure.mgmt.compute.models import (
    HardwareProfile,
    ImageReference,
    LinuxConfiguration,
    ManagedDiskParameters,
    NetworkInterfaceReference,
    NetworkProfile,
    OSDisk,
    OSProfile,
    SshConfiguration,
    SshPublicKey,
    StorageProfile,
    VirtualMachine,
)
from azure.mgmt.network.models import (
    AddressSpace,
    NatGateway,
    NatGatewaySku,
    NetworkInterface,
    NetworkInterfaceIPConfiguration,
    NetworkSecurityGroup,
    PublicIPAddress,
    PublicIPAddressSku,
    SecurityRule,
    Subnet,
    SubResource,
    VirtualNetwork,
)
from azure.mgmt.resource.resources.models import ResourceGroup

from src.lib import config
from src.lib.config import VmSpec
from src.lib.clients import clients
from src.lib.guest import new_database_password, run_shell, script_with_password
from src.lib.log import info, step
from src.lib.public_ip import operator_ipv4
from src.lib.retry import wait
from src.lib.sshkey import load_or_create_public_key


def rule(name, priority, access, protocol, dest_port, source) -> SecurityRule:
    return SecurityRule(
        name=name,
        priority=priority,
        access=access,
        direction="Inbound",
        protocol=protocol,
        source_port_range="*",
        destination_port_range=dest_port,
        source_address_prefix=source,
        destination_address_prefix="*",
        description=name.replace("-", " "),
    )


def nsg_rules(operator_ip: str) -> dict[str, list[SecurityRule]]:
    """Subnet firewall rules.

    The database allow rules sit above an explicit deny for the rest of the
    virtual network. Azure's built-in AllowVnetInBound rule (priority 65000)
    would otherwise let every virtual-network address through.
    """
    return {
        config.NSG_WEB: [
            rule("Allow-Http-Internet", 100, "Allow", "Tcp", "80", "*"),
            rule("Allow-Ssh-Operator", 110, "Allow", "Tcp", "22", f"{operator_ip}/32"),
        ],
        config.NSG_DB: [
            rule("Allow-Postgres-From-Web", 100, "Allow", "Tcp", str(config.DB_PORT), config.WEB_PREFIX),
            rule("Allow-Ssh-From-Web", 110, "Allow", "Tcp", "22", config.WEB_PREFIX),
            rule("Allow-Icmp-From-Web", 120, "Allow", "Icmp", "*", config.WEB_PREFIX),
            rule("Deny-Other-Vnet", 200, "Deny", "*", "*", "VirtualNetwork"),
        ],
        config.NSG_TEST: [
            rule("Allow-Ssh-From-Web", 100, "Allow", "Tcp", "22", config.WEB_PREFIX),
        ],
    }


def print_plan(operator_ip: str | None) -> None:
    step("Plan only. Nothing is created in Azure.")
    info(f"Resource group: {config.RESOURCE_GROUP} ({config.LOCATION})")
    info(f"Virtual network: {config.VNET_NAME} {config.VNET_PREFIX}")
    for subnet in config.SUBNETS:
        nat = f", NAT gateway {config.NAT_GATEWAY}" if subnet.attach_nat else ""
        info(f"Subnet {subnet.name} {subnet.prefix} with {subnet.nsg}{nat}")
    for vm in config.VMS:
        public = vm.public_ip or "no public IP"
        info(f"VM {vm.name} at {vm.private_ip} ({public})")
    ssh_source = f"{operator_ip}/32" if operator_ip else "your current public IPv4 address, read at deploy time"
    info(f"Web SSH allow rule source: {ssh_source}")
    info("Database password is generated in memory and is not printed or saved here.")


def ensure_vm(compute, spec: VmSpec, nic_id: str, public_key: str):
    try:
        compute.virtual_machines.get(config.RESOURCE_GROUP, spec.name)
        info(f"{spec.name} already exists. Leaving the virtual machine in place.")
        return
    except ResourceNotFoundError:
        pass

    vm = VirtualMachine(
        location=config.LOCATION,
        tags=config.TAGS,
        hardware_profile=HardwareProfile(vm_size=config.VM_SIZE),
        storage_profile=StorageProfile(
            image_reference=ImageReference(**config.IMAGE),
            os_disk=OSDisk(
                create_option="FromImage",
                managed_disk=ManagedDiskParameters(storage_account_type="StandardSSD_LRS"),
                delete_option="Delete",
                disk_size_gb=30,
            ),
        ),
        os_profile=OSProfile(
            computer_name=spec.name,
            admin_username=config.ADMIN_USER,
            linux_configuration=LinuxConfiguration(
                disable_password_authentication=True,
                ssh=SshConfiguration(
                    public_keys=[
                        SshPublicKey(
                            path=f"/home/{config.ADMIN_USER}/.ssh/authorized_keys",
                            key_data=public_key,
                        )
                    ]
                ),
            ),
        ),
        network_profile=NetworkProfile(
            network_interfaces=[
                NetworkInterfaceReference(id=nic_id, primary=True, delete_option="Delete")
            ]
        ),
    )
    poller = compute.virtual_machines.begin_create_or_update(
        config.RESOURCE_GROUP, spec.name, vm
    )
    wait(poller, spec.name)


def deploy(operator_ip: str) -> None:
    public_key = load_or_create_public_key()
    password = new_database_password()
    resource, network, compute = clients()

    step(f"Resource group {config.RESOURCE_GROUP}")
    resource.resource_groups.create_or_update(
        config.RESOURCE_GROUP,
        ResourceGroup(location=config.LOCATION, tags=config.TAGS),
    )

    step("Public IP addresses")
    web_pip = wait(
        network.public_ip_addresses.begin_create_or_update(
            config.RESOURCE_GROUP,
            config.PIP_WEB,
            PublicIPAddress(
                location=config.LOCATION,
                tags=config.TAGS,
                sku=PublicIPAddressSku(name="Standard"),
                public_ip_allocation_method="Static",
                public_ip_address_version="IPv4",
            ),
        ),
        config.PIP_WEB,
    )
    nat_pip = wait(
        network.public_ip_addresses.begin_create_or_update(
            config.RESOURCE_GROUP,
            config.PIP_NAT,
            PublicIPAddress(
                location=config.LOCATION,
                tags=config.TAGS,
                sku=PublicIPAddressSku(name="Standard"),
                public_ip_allocation_method="Static",
                public_ip_address_version="IPv4",
            ),
        ),
        config.PIP_NAT,
    )

    step(f"NAT gateway {config.NAT_GATEWAY}")
    nat = wait(
        network.nat_gateways.begin_create_or_update(
            config.RESOURCE_GROUP,
            config.NAT_GATEWAY,
            NatGateway(
                location=config.LOCATION,
                tags=config.TAGS,
                sku=NatGatewaySku(name="Standard"),
                idle_timeout_in_minutes=4,
                public_ip_addresses=[SubResource(id=nat_pip.id)],
            ),
        ),
        config.NAT_GATEWAY,
    )

    rules = nsg_rules(operator_ip)
    nsg_ids = {}
    for name, security_rules in rules.items():
        created = wait(
            network.network_security_groups.begin_create_or_update(
                config.RESOURCE_GROUP,
                name,
                NetworkSecurityGroup(
                    location=config.LOCATION,
                    tags=config.TAGS,
                    security_rules=security_rules,
                ),
            ),
            name,
        )
        nsg_ids[name] = created.id

    step(f"Virtual network {config.VNET_NAME}")
    wait(
        network.virtual_networks.begin_create_or_update(
            config.RESOURCE_GROUP,
            config.VNET_NAME,
            VirtualNetwork(
                location=config.LOCATION,
                tags=config.TAGS,
                address_space=AddressSpace(address_prefixes=[config.VNET_PREFIX]),
            ),
        ),
        config.VNET_NAME,
    )

    subnet_ids = {}
    for spec in config.SUBNETS:
        subnet = Subnet(
            address_prefix=spec.prefix,
            network_security_group=NetworkSecurityGroup(id=nsg_ids[spec.nsg]),
            default_outbound_access=False,
        )
        if spec.attach_nat:
            subnet.nat_gateway = SubResource(id=nat.id)
        created = wait(
            network.subnets.begin_create_or_update(
                config.RESOURCE_GROUP,
                config.VNET_NAME,
                spec.name,
                subnet,
            ),
            spec.name,
        )
        subnet_ids[spec.name] = created.id

    nic_ids = {}
    pip_ids = {config.PIP_WEB: web_pip.id}
    for spec in config.VMS:
        ip_config = NetworkInterfaceIPConfiguration(
            name="ipconfig1",
            subnet=Subnet(id=subnet_ids[spec.subnet]),
            private_ip_allocation_method="Static",
            private_ip_address=spec.private_ip,
        )
        if spec.public_ip:
            ip_config.public_ip_address = PublicIPAddress(id=pip_ids[spec.public_ip])
        nic = wait(
            network.network_interfaces.begin_create_or_update(
                config.RESOURCE_GROUP,
                spec.nic,
                NetworkInterface(
                    location=config.LOCATION,
                    tags=config.TAGS,
                    ip_configurations=[ip_config],
                ),
            ),
            spec.nic,
        )
        nic_ids[spec.name] = nic.id

    for spec in config.VMS:
        ensure_vm(compute, spec, nic_ids[spec.name], public_key)

    step("Install PostgreSQL on the database VM")
    db_output = run_shell(
        compute,
        config.RESOURCE_GROUP,
        config.VM_DB,
        script_with_password("db-setup.sh", password),
        password,
    )
    if "DB_READY" not in db_output:
        raise SystemExit("PostgreSQL setup did not finish. The password was not printed.")

    step("Install the web page")
    web_output = run_shell(
        compute,
        config.RESOURCE_GROUP,
        config.VM_WEB,
        script_with_password("web-setup.sh", password),
        password,
    )
    if "WEB_READY" not in web_output:
        raise SystemExit("Web setup did not finish. The password was not printed.")

    web_pip = network.public_ip_addresses.get(config.RESOURCE_GROUP, config.PIP_WEB)
    address = web_pip.ip_address or "(public IP still empty; check pip-web-01 in the portal)"
    step("Deploy finished")
    info(f"Web page: http://{address}/")
    info(
        f"SSH to the web VM: ssh -i keys/id_ed25519 {config.ADMIN_USER}@{address}"
    )
    info(
        "SSH to the database VM through the web VM: "
        f"ssh -i keys/id_ed25519 -J {config.ADMIN_USER}@{address} "
        f"{config.ADMIN_USER}@{config.DB_PRIVATE_IP}"
    )
    info(f"Web SSH is limited to {operator_ip}/32")
    info("Next: python -m src.verify")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy the two-tier network proof of concept.")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the resources and exit. Does not call Azure.",
    )
    args = parser.parse_args()
    if args.plan:
        print_plan(None)
        return
    operator_ip = operator_ipv4()
    info(f"Web SSH allow rule will use {operator_ip}/32")
    deploy(operator_ip)


if __name__ == "__main__":
    main()
