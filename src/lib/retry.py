"""Waits and retries for Azure operations that are slow or briefly unavailable."""

import time

from azure.core.exceptions import HttpResponseError

from src.lib.log import info, step


def wait(poller, label: str, timeout: int = 1800):
    """Block until a long-running Azure operation finishes."""
    step(f"Waiting for {label}")
    result = poller.result(timeout=timeout)
    info(f"Ready: {label}")
    return result


def call_with_retry(action, label: str, attempts: int = 8, delay_seconds: int = 20):
    """Retry when the VM agent is not ready yet or Azure asks us to slow down.

    The original exception is not re-raised. Azure error text can echo the
    script that was sent, and that script holds the database password.
    """
    last_status = "unknown"
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except HttpResponseError as exc:
            last_status = str(getattr(exc, "status_code", "unknown"))
            retryable = last_status in {"409", "429", "500", "502", "503"}
            if not retryable or attempt == attempts:
                raise RuntimeError(
                    f"{label} failed (HTTP {last_status}). "
                    "Details were not printed, because the request can contain the database password."
                ) from None
            info(f"{label} is not ready (HTTP {last_status}). Retry {attempt} of {attempts - 1}.")
            time.sleep(delay_seconds)
    raise RuntimeError(f"{label} failed (HTTP {last_status}).")
