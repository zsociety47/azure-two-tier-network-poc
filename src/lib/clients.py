"""Azure clients signed in with DefaultAzureCredential.

DefaultAzureCredential uses the existing `az login` session. No password is
stored in this repository.
"""

import json
import os
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource.resources import ResourceManagementClient

from src.lib.log import info


def subscription() -> tuple[str, str]:
    """Return (subscription id, display name) for the signed-in account.

    AZURE_SUBSCRIPTION_ID wins when it is set. Otherwise the default entry in
    the local Azure CLI profile is used. Only the id and name are read.
    """
    chosen = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if chosen:
        return chosen, "AZURE_SUBSCRIPTION_ID"

    profile = Path.home() / ".azure" / "azureProfile.json"
    if not profile.exists():
        raise SystemExit(
            "No Azure subscription selected. Run `az login`, or set AZURE_SUBSCRIPTION_ID."
        )
    data = json.loads(profile.read_text(encoding="utf-8-sig"))
    subscriptions = data.get("subscriptions") or []
    defaults = [item for item in subscriptions if item.get("isDefault") and item.get("id")]
    if len(defaults) != 1:
        raise SystemExit(
            "Could not find one default Azure subscription. Set AZURE_SUBSCRIPTION_ID and run again."
        )
    return str(defaults[0]["id"]), str(defaults[0].get("name") or "default")


def clients():
    """Build the resource, network, and compute clients for one subscription."""
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    subscription_id, subscription_name = subscription()
    info(f"Subscription: {subscription_name}")
    return (
        ResourceManagementClient(credential, subscription_id),
        NetworkManagementClient(credential, subscription_id),
        ComputeManagementClient(credential, subscription_id),
    )
