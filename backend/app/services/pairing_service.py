"""Phone pairing: find the addresses another device could use to reach this
machine (LAN and Tailscale) and check whether the backend is actually
listening on them, so Settings can show a QR code plus what's still missing."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess


def _lan_ip() -> str | None:
    # UDP "connect" sends nothing; it just makes the OS pick the outbound interface.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


def _tailscale() -> tuple[str | None, str | None]:
    """(ipv4, MagicDNS name) of this machine on the tailnet, if Tailscale runs."""
    exe = shutil.which("tailscale")
    if not exe:
        return None, None
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=4, check=True).stdout
        me = json.loads(out).get("Self") or {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None
    ips = [ip for ip in me.get("TailscaleIPs") or [] if ":" not in ip]
    name = (me.get("DNSName") or "").rstrip(".") or None
    return (ips[0] if ips else None), name


def listening_on(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=0.5):
            return True
    except OSError:
        return False


def addresses() -> list[dict]:
    out = []
    ts_ip, ts_name = _tailscale()
    if ts_name:
        out.append({"kind": "tailscale", "host": ts_name, "ip": ts_ip})
    elif ts_ip:
        out.append({"kind": "tailscale", "host": ts_ip, "ip": ts_ip})
    lan = _lan_ip()
    if lan:
        out.append({"kind": "lan", "host": lan, "ip": lan})
    return out
