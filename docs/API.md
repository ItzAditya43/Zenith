# Zenith's API

Everything the app does goes through a local HTTP API, so scripts and other
apps can use it too. The full, always-current list of endpoints is the
OpenAPI schema served by your own instance:

- `http://127.0.0.1:8420/docs` — browsable reference
- `http://127.0.0.1:8420/openapi.json` — machine-readable schema

**Version.** Every `/api/` response carries `X-Zenith-API-Version` (currently
`1`), and `GET /api/version` returns it with the app version. The endpoints
listed under "Stable" below keep their shape within an API version; anything
else may change between releases.

## Access

| From | What you need |
|---|---|
| This machine | Nothing, unless you turned on the passcode lock or shared-secret auth |
| Another device / a script elsewhere | An **API key**, or the passcode / shared secret |

**API keys** (Settings → Data → API keys) are the way to give a script access:

- `read` keys can only `GET`; `write` keys can do anything the app can.
- A key is shown **once** — only a hash is stored. Lost it? Rotate it.
- Send it as `Authorization: Bearer zk_…`.
- A valid key works from other devices and while the passcode lock is on,
  because it's an explicit grant you made. Keys can't create or manage keys.
- Each key is limited to `api_key_rate_per_minute` requests (default 120);
  over that you get `429` with `Retry-After`.
- **Rotation:** "Rotate" gives a new key with the same name and scope and
  stops the old one immediately. "Revoke" just stops it.

Errors are JSON: `{"detail": "...", "code": "..."}` with a normal HTTP status
(`401` bad key, `403` read-only key / remote access blocked, `423` locked,
`429` rate limited).

## Stable endpoints (API version 1)

| Purpose | Endpoint |
|---|---|
| Version | `GET /api/version` |
| Health | `GET /api/health` |
| Models | `GET /api/models` |
| Conversations | `GET /api/conversations`, `POST /api/conversations {title}`, `GET /api/conversations/{id}/messages`, `DELETE /api/conversations/{id}` |
| Chat (streaming) | `POST /api/chat {conversation_id, message, attachment_ids?, model_override?, web_search?, deep_research?, agent_mode_on?}` |
| Files | `POST /api/upload` (multipart `file`, optional `conversation_id`) |
| Memory | `GET /api/memories/browse?q=`, `POST /api/memories {content}` |
| Events | `GET /api/notifications?since=<unix>` — finished schedules and background tasks, digests, urgent mail… |
| Background tasks | `POST /api/agent/background {conversation_id, prompt}`, `GET /api/agent/background/{id}` |

### Chat streaming

`POST /api/chat` answers with Server-Sent Events: lines of `data: {json}`
separated by blank lines. Event `type`s include `route` (which model was
picked and why), `sources`, `token` (`text`), `done` and `error`
(`message`). A `:heartbeat` comment arrives periodically on long streams.

```bash
KEY=zk_...
CID=$(curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"title":"From curl"}' http://127.0.0.1:8420/api/conversations | jq -r .id)
curl -N -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "{\"conversation_id\":\"$CID\",\"message\":\"Hello\"}" http://127.0.0.1:8420/api/chat
```

## Clients

Small, dependency-free clients live in [`examples/clients/`](../examples/clients):

- **Python** — `zenith_client.py` (standard library only):
  ```python
  from zenith_client import Zenith
  z = Zenith("http://127.0.0.1:8420", key="zk_...")
  cid = z.new_chat("From a script")["id"]
  for text in z.chat(cid, "Give me three ideas for dinner"):
      print(text, end="")
  ```
- **TypeScript / JavaScript** — `zenith.ts` (uses `fetch`; browsers, Node 18+, Deno, Bun):
  ```ts
  const z = new Zenith("http://127.0.0.1:8420", "zk_...");
  const { id } = await z.newChat("From a script");
  for await (const text of z.chat(id, "Hello")) process.stdout.write(text);
  ```

Both cover chat streaming, conversations, uploads, models and events.
