"""Install PostgreSQL and the web page with Azure VM Run Command."""

import secrets
from pathlib import Path

from azure.mgmt.compute.models import RunCommandInput

from src.lib.log import info
from src.lib.retry import call_with_retry, wait

GUEST_DIR = Path(__file__).resolve().parents[1] / "guest"
PASSWORD_TOKEN = "__DB_PASSWORD__"


def new_database_password() -> str:
    """Create a password that is safe to embed in a SQL string.

    token_urlsafe uses letters, digits, hyphen, and underscore, so it needs
    no extra quoting. The value stays in memory and is never printed.
    """
    return secrets.token_urlsafe(24)


def script_with_password(filename: str, password: str) -> list[str]:
    """Load a guest script and substitute the database password."""
    body = (GUEST_DIR / filename).read_text(encoding="utf-8")
    if PASSWORD_TOKEN not in body:
        raise SystemExit(f"{filename} is missing the {PASSWORD_TOKEN} placeholder.")
    filled = body.replace(PASSWORD_TOKEN, password)
    return filled.splitlines()


def redact(text: str, password: str) -> str:
    if not password:
        return text
    return text.replace(password, "[redacted]")


def command_text(result) -> str:
    parts = []
    for status in result.value or []:
        message = getattr(status, "message", None)
        if message:
            parts.append(message)
    return "\n".join(parts)


def run_shell(compute, resource_group: str, vm_name: str, script: list[str], password: str) -> str:
    """Run a shell script on a VM and return its output with the password removed."""

    def start():
        poller = compute.virtual_machines.begin_run_command(
            resource_group,
            vm_name,
            RunCommandInput(command_id="RunShellScript", script=script),
        )
        return wait(poller, f"run command on {vm_name}", timeout=1200)

    result = call_with_retry(start, f"Run command on {vm_name}")
    output = redact(command_text(result), password)
    tail = "\n".join(output.splitlines()[-12:])
    if tail:
        info(tail)
    return output
