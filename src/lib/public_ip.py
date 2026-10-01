"""Detect the operator's current public IPv4 address for the SSH allow rule."""

import ipaddress
import urllib.request


def operator_ipv4() -> str:
    """Return this machine's current public IPv4 address.

    The address is placed on the web subnet's SSH rule at deploy time. It is
    not written into the repository.
    """
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as response:
            raw = response.read().decode("ascii").strip()
    except OSError as exc:
        raise SystemExit(
            "Could not read this machine's public IPv4 address from api.ipify.org. "
            "Check the network connection and run again."
        ) from exc
    try:
        ipaddress.IPv4Address(raw)
    except ipaddress.AddressValueError as exc:
        raise SystemExit("The public address lookup did not return an IPv4 address.") from exc
    return raw
