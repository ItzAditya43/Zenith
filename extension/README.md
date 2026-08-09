# Zenith Clipper (browser extension)

A minimal Manifest V3 extension that sends the current page (or a text
selection) into your own local Zenith instance — not published to any
extension store, load it unpacked from this folder.

## What it does

- **Send this page** — creates a new Zenith conversation and asks it to
  read and summarize the current tab's URL. Zenith's existing URL-reading
  feature (`web_service.py`) does the actual fetching/extraction — the
  extension just hands it the link.
- **Send selected text** — grabs whatever text is highlighted on the
  page and sends it as a message, with the source URL for context.

Either way, the extension fires the request and closes — it doesn't wait
for or display the reply. Open Zenith itself to read it. This is
deliberate: Zenith's backend keeps generating a reply independently of
whatever connection started it (see `stream_registry.py`), so there's
nothing the extension needs to stay open or poll for.

## Install (unpacked — this isn't in the Chrome/Edge/Firefox store)

1. Build the desktop app or run the Docker/manual backend so something is
   listening on `http://localhost:8420` (see the main [README](../README.md)).
2. **Chrome / Edge / Brave**: go to `chrome://extensions` (or
   `edge://extensions`), enable **Developer mode**, click **Load unpacked**,
   and select this `extension/` folder.
3. **Firefox**: go to `about:debugging#/runtime/this-firefox`, click
   **Load Temporary Add-on**, and select `manifest.json` in this folder.
   (Temporary add-ons are removed when Firefox restarts — Firefox doesn't
   support persistent unpacked MV3 extensions the same way.)
4. Click the Zenith icon in your browser toolbar to open the popup.

## Configuration

The popup has a **Zenith backend URL** field (defaults to
`http://localhost:8420`). If you're running Zenith on a different port,
or reaching it over your LAN (see [MULTIDEVICE.md](../MULTIDEVICE.md)),
change it there — it's saved in the extension's local storage.

Changing the URL to something outside `localhost`/`127.0.0.1` on port
`8420` requires also adding a matching entry to `host_permissions` in
`manifest.json` and reloading the unpacked extension — Chrome's
extension permission model is static per-manifest, so an arbitrary
runtime URL can't be granted CORS-bypass access without that. This is a
known, documented limitation of keeping the extension this minimal
(no options page, no runtime permission prompts).

## Why no build step

No bundler, no framework, no npm dependency — three plain files
(`manifest.json`, `popup.html`, `popup.js`) using the extension APIs
directly. There's exactly one feature here; a build pipeline would be
pure overhead.
