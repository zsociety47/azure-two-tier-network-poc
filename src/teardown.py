"""Delete the proof of concept resource group after you type its name.

Run from the repository root:

    python -m src.teardown
"""

from azure.core.exceptions import ResourceNotFoundError

from src.lib.clients import clients
from src.lib.config import RESOURCE_GROUP
from src.lib.log import info, step
from src.lib.retry import wait


def main() -> None:
    print(f"This deletes {RESOURCE_GROUP} and every resource inside it.")
    print("Virtual machines, public IP addresses, the NAT gateway, and disks go with it.")
    typed = input(f"Type {RESOURCE_GROUP} to continue: ").strip()
    if typed != RESOURCE_GROUP:
        raise SystemExit("The name did not match. Nothing was deleted.")

    resource, _network, _compute = clients()
    try:
        resource.resource_groups.get(RESOURCE_GROUP)
    except ResourceNotFoundError:
        info(f"{RESOURCE_GROUP} is already gone.")
        return

    step(f"Deleting {RESOURCE_GROUP}")
    info("This often takes several minutes.")
    wait(resource.resource_groups.begin_delete(RESOURCE_GROUP), RESOURCE_GROUP, timeout=3600)
    try:
        resource.resource_groups.get(RESOURCE_GROUP)
    except ResourceNotFoundError:
        step("Teardown finished. The resource group is gone.")
        return
    raise SystemExit(f"{RESOURCE_GROUP} still exists. Check the portal before assuming it is gone.")


if __name__ == "__main__":
    main()
