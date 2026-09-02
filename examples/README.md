# Zenith examples

Copy-paste starting points for two of Zenith's less discoverable but genuinely
powerful features: MCP server configs and automation rules. Everything here
is real, working JSON matching the exact request shapes the backend expects
— not illustrative pseudo-JSON.

## `mcp-servers/`

Each file matches `MCPServerCreate` (`backend/app/models/schemas.py`):
`name`, `command`, `args` (list of strings), `env` (string->string map). These
are the same servers listed as the curated "Popular servers" chips in
Settings -> Agent tools -> MCP servers (see README.md's "MCP client support"
section), reproduced here as ready-to-use files instead of UI-only chips.

To use one:

- **Via the UI**: Settings -> Agent tools -> MCP servers -> Add server, and
  fill in the `name` / `command` / `args` / `env` fields from the JSON file
  (or just click the matching pre-fill chip if it's one of the curated ones).
- **Via the API**: POST the file's contents directly to `/api/mcp/servers`,
  e.g.:

  ```bash
  curl -X POST http://localhost:8000/api/mcp/servers \
    -H "Content-Type: application/json" \
    -d @examples/mcp-servers/fetch.json
  ```

Notes:

- `filesystem.json` grants read/write access to one directory — edit the
  `/path/to/allow` argument to an actual path on your machine before adding
  it. Don't point it at your whole home directory.
- `fetch.json` and `git.json` work as-is, no editing required (`git.json`
  needs `uv`/`uvx` installed; `fetch.json` and `filesystem.json` need `npx`
  from a Node.js install).
- MCP tools are always classified **risky** in Zenith's approval model
  regardless of which server they come from — you'll be prompted before an
  agent turn actually calls one.

## `automation-rules/`

Each file matches `AutomationRuleCreate` (`backend/app/models/schemas.py`):
`name`, `trigger_type`, `trigger_config`, `action_type`, `action_config`.
`trigger_type` must be one of the real event types in
`backend/app/services/events.py`'s `EVENT_TYPES`
(`digest_generated`, `schedule_completed`, `urgent_email`,
`memory_conflict_found`, `folder_file_added`). `action_type` is either
`"prompt"` (send a message into a persistent conversation, chat or research
mode only — never agent mode) or `"webhook"` (POST the event payload to one
URL).

To use one:

- **Via the UI**: Settings -> Automation -> New rule, and fill in the fields
  from the JSON file.
- **Via the API**: POST the file's contents directly to
  `/api/automation/rules`, e.g.:

  ```bash
  curl -X POST http://localhost:8000/api/automation/rules \
    -H "Content-Type: application/json" \
    -d @examples/automation-rules/summarize-new-file.json
  ```

What each one demonstrates:

- `summarize-new-file.json` — on `folder_file_added` (filtered to one folder
  via `trigger_config.folder_id`, which you must replace with a real watched
  folder's id), send a prompt into a persistent conversation asking for a
  summary of the new file. `{event_data}` in the prompt is substituted with
  the triggering event's JSON at fire time.
- `schedule-completed-webhook.json` — on `schedule_completed`, POST the event
  payload to a webhook URL (replace with your own receiver).
- `urgent-email-prompt.json` — on `urgent_email`, send a prompt into a
  persistent conversation asking for a draft reply.
