# Using Zenith from other devices

Zenith runs one backend on one machine; other devices (a phone, a laptop, a
tablet) reach that same backend over your network. This is **shared access to
one instance**, not multi-master sync — see the note at the bottom.

## Before you start: how exposure works

By default Zenith only listens on `127.0.0.1`, so nothing else on your
network can reach it. Opening it up takes three deliberate steps, and the
backend enforces the last one:

1. **Listen on the network.** Start the backend with `ZENITH_BIND=0.0.0.0`
   (`run.sh` / `run.ps1` / `docker compose` all honour it; the desktop app
   uses the same variable).
2. **Allow the origin.** Settings → Connection → **Allow LAN/Tailscale
   access** widens CORS to private-network and `*.ts.net` origins.
3. **Set a passcode** (Settings → Data) or shared-secret auth. Until one
   exists, every request that doesn't come from the host machine itself
   gets `403 Remote access is blocked` — CORS only stops browsers, and
   agent mode can run shell commands, so "anyone on the Wi-Fi" is never
   allowed in ungated.

## Same Wi-Fi / LAN

1. Find the host machine's LAN IP (e.g. `192.168.1.20`).
2. Do the three steps above.
3. On the other device, open `http://192.168.1.20:5173` and enter the
   passcode.

The frontend auto-detects that it was loaded from `192.168.1.20` and talks to
the backend at `192.168.1.20:8420` — no rebuild or config needed (it no longer
hard-codes `localhost`). Install it to your phone's home screen for an app-like
experience (see the PWA support — Add to Home Screen).

## Remote (anywhere) via Tailscale

For access outside your LAN without exposing anything to the public internet,
put both devices on a [Tailscale](https://tailscale.com) tailnet (free for
personal use, self-hostable via Headscale):

1. Install Tailscale on the host and your other device.
2. Open `http://<host-machine-name>.ts.net:5173` on the other device.

`*.ts.net` origins are covered by the LAN/Tailscale CORS toggle above.

## Gates

Remote devices need **at least one** of these (the backend refuses them
otherwise):

- **Passcode lock** (Settings → Data) — a login gate for the UI/API. Wrong
  guesses back off exponentially (5 free tries, then 30s doubling up to 15
  minutes).
- **Shared-secret auth** (`AUTH_ENABLED=true` + `AUTH_SHARED_SECRET=...` env,
  or `auth_enabled` / `auth_shared_secret` in `config.json`) — a bearer token
  required on every request. The UI asks for it once per device.

Tailscale additionally keeps traffic on an encrypted, private tailnet.

### Reverse proxies and custom hostnames

Requests from the host machine must use `localhost`, a `*.localhost` name or
a literal IP in the `Host` header — this blocks DNS-rebinding attacks, where a
malicious web page points its own domain at `127.0.0.1`. If you front Zenith
with a proxy on the same machine under a real hostname, add it to
`ZENITH_ALLOWED_HOSTS` (comma-separated) or `allowed_hosts` in `config.json`.

## What this is *not*: true multi-device sync

Every device here is a thin client of the **one** backend and its **one**
SQLite database — so history is naturally consistent because there's a single
source of truth. What's intentionally out of scope is **multi-master sync**:
several independent Zenith instances (each with their own DB) reconciling
conversations offline and merging on reconnect. That needs a real
conflict-resolution layer (CRDTs or a sync server) and is a much larger project
than "let my phone use my desktop's Zenith," which is what the above delivers.
