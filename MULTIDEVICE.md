# Using Zenith from other devices

Zenith runs one backend on one machine; other devices (a phone, a laptop, a
tablet) reach that same backend over your network. This is **shared access to
one instance**, not multi-master sync — see the note at the bottom.

## Same Wi-Fi / LAN

1. Find the host machine's LAN IP (e.g. `192.168.1.20`).
2. In Zenith → Settings → Connection, turn on **Allow LAN/Tailscale access**
   (this widens CORS to accept private-network and `*.ts.net` origins).
3. On the other device, open `http://192.168.1.20:5173`.

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

## Secure it

Opening the backend beyond `localhost` means other devices on that network can
reach the API. Turn on **at least one** of:

- **Passcode lock** (Settings → Data) — a login gate for the UI/API.
- **Shared-secret auth** (`AUTH_ENABLED` + `AUTH_SHARED_SECRET` env) — a bearer
  token required on every request, for a fixed deployment.

Tailscale additionally keeps traffic on an encrypted, private tailnet.

## What this is *not*: true multi-device sync

Every device here is a thin client of the **one** backend and its **one**
SQLite database — so history is naturally consistent because there's a single
source of truth. What's intentionally out of scope is **multi-master sync**:
several independent Zenith instances (each with their own DB) reconciling
conversations offline and merging on reconnect. That needs a real
conflict-resolution layer (CRDTs or a sync server) and is a much larger project
than "let my phone use my desktop's Zenith," which is what the above delivers.
