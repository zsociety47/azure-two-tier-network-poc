"""Run the success checks and print a pass/fail table.

Run from the repository root, after deploy:

    python -m src.verify

After teardown:

    python -m src.verify --after-teardown
"""

import argparse
import urllib.error
import urllib.request

from azure.core.exceptions import ResourceNotFoundError
from azure.mgmt.compute.models import RunCommandInput

from src.lib import config
from src.lib.clients import clients
from src.lib.guest import command_text
from src.lib.log import info, step
from src.lib.retry import wait

TCP_SCRIPT = f"""
timeout 8 bash -c 'echo >/dev/tcp/{config.DB_PRIVATE_IP}/{config.DB_PORT}'
code=$?
if [ "$code" -eq 0 ]; then
  echo RESULT=open
elif [ "$code" -eq 124 ]; then
  echo RESULT=timeout
else
  echo RESULT=refused
fi
""".strip().splitlines()


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    inner = getattr(value, "value", None)
    if isinstance(inner, str):
        return inner
    return str(value)


def nic_has_public_ip(nic) -> bool:
    for item in nic.ip_configurations or []:
        public = item.public_ip_address
        if public is not None and public.id:
            return True
    return False


def tcp_result(compute, vm_name: str) -> str:
    poller = compute.virtual_machines.begin_run_command(
        config.RESOURCE_GROUP,
        vm_name,
        RunCommandInput(command_id="RunShellScript", script=TCP_SCRIPT),
    )
    output = command_text(wait(poller, f"TCP check on {vm_name}", timeout=300))
    for line in output.splitlines():
        if "RESULT=" in line:
            return line.strip().split("RESULT=", 1)[1].strip()
    return "unknown"


def web_page(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            code = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}"
    except OSError as exc:
        return False, exc.__class__.__name__
    if code == 200 and config.PAGE_MARKER in body:
        return True, "HTTP 200 and the page shows the database"
    return False, f"HTTP {code}, marker missing"


def ssh_locked_to_web(rules) -> tuple[bool, str]:
    """Database SSH is allowed from the web subnet, and not from the internet."""
    allows_web = False
    denies_other_vnet = False
    open_to_internet = False
    internet_sources = {"*", "Internet", "0.0.0.0/0"}
    for item in rules or []:
        if as_text(item.direction) != "Inbound":
            continue
        access = as_text(item.access)
        protocol = as_text(item.protocol)
        dest = as_text(item.destination_port_range)
        source = as_text(item.source_address_prefix)
        covers_ssh = protocol in {"Tcp", "*"} and dest in {"22", "*"}
        if access == "Allow" and covers_ssh and source == config.WEB_PREFIX:
            allows_web = True
        if access == "Allow" and covers_ssh and source in internet_sources:
            open_to_internet = True
        if (
            access == "Deny"
            and source == "VirtualNetwork"
            and as_text(item.priority) == "200"
        ):
            denies_other_vnet = True
    if allows_web and denies_other_vnet and not open_to_internet:
        return True, "SSH from the web subnet only, then other virtual-network traffic is denied"
    return False, "database SSH rules do not match the expected allow and deny"


def print_table(rows: list[tuple[str, str, str]]) -> bool:
    step("Results")
    print(f"{'#':<4} {'Check':<52} {'Result'}")
    print("-" * 72)
    failed = False
    for number, label, result in rows:
        print(f"{number:<4} {label:<52} {result}")
        if result.startswith("FAIL"):
            failed = True
    print("-" * 72)
    return not failed


def after_teardown() -> None:
    resource, _network, _compute = clients()
    try:
        resource.resource_groups.get(config.RESOURCE_GROUP)
        gone = False
    except ResourceNotFoundError:
        gone = True
    ok = print_table([
        (
            "6",
            "Teardown leaves nothing behind",
            "PASS" if gone else f"FAIL  {config.RESOURCE_GROUP} still exists",
        )
    ])
    if not ok:
        raise SystemExit(1)


def verify() -> None:
    resource, network, compute = clients()
    try:
        resource.resource_groups.get(config.RESOURCE_GROUP)
    except ResourceNotFoundError:
        raise SystemExit(
            f"{config.RESOURCE_GROUP} does not exist. Deploy first, or use --after-teardown."
        )

    web_pip = network.public_ip_addresses.get(config.RESOURCE_GROUP, config.PIP_WEB)
    address = web_pip.ip_address or ""
    if address:
        page_ok, page_detail = web_page(f"http://{address}/")
    else:
        page_ok, page_detail = False, "web public IP has no address yet"

    db_nic = network.network_interfaces.get(config.RESOURCE_GROUP, config.NIC_DB)
    private_only = not nic_has_public_ip(db_nic)

    web_tcp = tcp_result(compute, config.VM_WEB)
    test_tcp = tcp_result(compute, config.VM_TEST)

    db_nsg = network.network_security_groups.get(config.RESOURCE_GROUP, config.NSG_DB)
    ssh_ok, ssh_detail = ssh_locked_to_web(db_nsg.security_rules)
    ssh_ok = ssh_ok and private_only
    if not private_only:
        ssh_detail = "database NIC still has a public IP"

    rows = [
        ("1", "Web page loads and shows the database", "PASS" if page_ok else f"FAIL  {page_detail}"),
        ("2", "Database VM has no public IP", "PASS" if private_only else "FAIL  public IP present"),
        ("3", "Web VM reaches database port 5432", "PASS" if web_tcp == "open" else f"FAIL  {web_tcp}"),
        (
            "4",
            "Test VM is blocked on port 5432",
            "PASS" if test_tcp == "timeout" else f"FAIL  {test_tcp}",
        ),
        ("5", "Database SSH only from the web subnet", "PASS" if ssh_ok else f"FAIL  {ssh_detail}"),
        ("6", "Teardown leaves nothing behind", "NOT RUN  python -m src.teardown, then --after-teardown"),
    ]
    info(f"Web page address: http://{address or 'unknown'}/")
    ok = print_table(rows)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the two-tier network proof of concept.")
    parser.add_argument(
        "--after-teardown",
        action="store_true",
        help="Check that the resource group is gone.",
    )
    args = parser.parse_args()
    if args.after_teardown:
        after_teardown()
        return
    verify()


if __name__ == "__main__":
    main()
