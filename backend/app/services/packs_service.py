"""Prompt templates and shareable feature packs.

Templates: a quick action's text can hold fields like {{topic}} or
{{tone|friendly}} (a default after the bar). Running it asks for the
fields first; {{date}} and {{time}} fill themselves. `template_fields`
checks the syntax so a broken template is refused when it's saved,
not when it's used.

Packs: a JSON file (format "zenith-pack") that bundles quick actions,
personas and automation rules so they can be shared. Importing is two
steps — a preview that lists what would be added, what's already there,
and what each item is allowed to do (rules that call a webhook, actions
that send without asking, personas that change instructions) — then the
import of the items the user kept. Nothing in a pack can run code or
reach the network on its own beyond what those rule types already do.
"""
from __future__ import annotations

import re
import time
from typing import Any

PACK_FORMAT = "zenith-pack"
PACK_VERSION = 1
AUTO_FIELDS = {"date", "time"}
_FIELD = re.compile(r"\{\{\s*([^{}|]*?)\s*(?:\|\s*([^{}]*?)\s*)?\}\}")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{0,39}$")
MAX_ITEMS = 200


def template_fields(text: str) -> list[dict]:
    """[{name, default}] in order of first use. Raises ValueError for an
    unclosed or malformed field."""
    stripped = _FIELD.sub("", text)
    if "{{" in stripped or "}}" in stripped:
        raise ValueError("A field isn't closed — fields look like {{name}} or {{name|default}}.")
    out: list[dict] = []
    seen: set[str] = set()
    for m in _FIELD.finditer(text):
        name, default = m.group(1), m.group(2)
        if not _NAME.match(name or ""):
            raise ValueError(f"“{name}” isn't a usable field name (letters, digits, spaces, - or _).")
        key = name.lower()
        if key in seen or key in AUTO_FIELDS:
            continue
        seen.add(key)
        out.append({"name": name, "default": default})
    return out


def fill_template(text: str, values: dict[str, str], now: float | None = None) -> str:
    lt = time.localtime(time.time() if now is None else now)
    auto = {"date": time.strftime("%Y-%m-%d", lt), "time": time.strftime("%H:%M", lt)}
    lower = {k.lower(): v for k, v in values.items()}

    def sub(m: re.Match) -> str:
        key = m.group(1).lower()
        if key in auto and key not in lower:
            return auto[key]
        val = lower.get(key)
        return val if val not in (None, "") else (m.group(2) or "")

    return _FIELD.sub(sub, text)


# ---- packs ----------------------------------------------------------------------------

def export_pack(name: str, description: str = "", quick_action_ids: list[str] | None = None,
                persona_ids: list[str] | None = None, rule_ids: list[str] | None = None) -> dict:
    from app.db import storage
    from app.services import persona_service

    qa = [q for q in storage.list_quick_actions() if quick_action_ids is None or q["id"] in quick_action_ids]
    pe = [p for p in persona_service.list_personas() if persona_ids is None or p["id"] in persona_ids]
    ru = [r for r in storage.list_automation_rules() if rule_ids is None or r["id"] in rule_ids]
    return {
        "format": PACK_FORMAT, "version": PACK_VERSION, "name": name.strip() or "My Zenith pack",
        "description": description.strip(), "created_at": time.time(),
        "items": {
            "quick_actions": [{"name": q["name"], "prompt_template": q["prompt_template"], "auto_send": bool(q["auto_send"])} for q in qa],
            "personas": [{"name": p["name"], "system_prompt": p.get("system_prompt") or "", "icon": p.get("icon")} for p in pe],
            "automation_rules": [{"name": r["name"], "trigger_type": r["trigger_type"], "trigger_config": r.get("trigger_config") or {},
                                  "action_type": r["action_type"], "action_config": r.get("action_config") or {}} for r in ru],
        },
    }


def _validate(pack: Any) -> dict:
    if not isinstance(pack, dict) or pack.get("format") != PACK_FORMAT:
        raise ValueError("That isn't a Zenith pack file.")
    if int(pack.get("version") or 0) > PACK_VERSION:
        raise ValueError("This pack was made by a newer Zenith. Update to import it.")
    items = pack.get("items")
    if not isinstance(items, dict):
        raise ValueError("The pack has no items.")
    total = sum(len(items.get(k) or []) for k in ("quick_actions", "personas", "automation_rules"))
    if total > MAX_ITEMS:
        raise ValueError(f"Packs are limited to {MAX_ITEMS} items.")
    return items


def preview_pack(pack: Any) -> dict:
    """What an import would do, item by item, without changing anything."""
    from app.db import storage
    from app.services import persona_service
    from app.services.events import EVENT_TYPES

    items = _validate(pack)
    have_qa = {(q["name"].lower(), q["prompt_template"]) for q in storage.list_quick_actions()}
    have_pe = {p["name"].lower() for p in persona_service.list_personas()}
    have_ru = {r["name"].lower() for r in storage.list_automation_rules()}
    out: list[dict] = []

    for i, q in enumerate(items.get("quick_actions") or []):
        name, tpl = str(q.get("name") or "").strip()[:100], str(q.get("prompt_template") or "").strip()[:5000]
        problem, notes = None, []
        if not name or not tpl:
            problem = "Missing a name or text."
        else:
            try:
                fields = template_fields(tpl)
                if fields:
                    notes.append("asks for " + ", ".join(f["name"] for f in fields))
            except ValueError as exc:
                problem = str(exc)
        if q.get("auto_send"):
            notes.append("sends as soon as you pick it")
        out.append({"kind": "quick_action", "index": i, "name": name, "detail": tpl[:240],
                    "duplicate": (name.lower(), tpl) in have_qa, "problem": problem, "permissions": notes})

    for i, p in enumerate(items.get("personas") or []):
        name, prompt = str(p.get("name") or "").strip()[:80], str(p.get("system_prompt") or "").strip()
        out.append({"kind": "persona", "index": i, "name": name, "detail": prompt[:240],
                    "duplicate": name.lower() in have_pe, "problem": None if name and prompt else "Missing a name or instructions.",
                    "permissions": ["changes the assistant's standing instructions when you choose it"]})

    for i, r in enumerate(items.get("automation_rules") or []):
        name = str(r.get("name") or "").strip()[:100]
        trig, act = r.get("trigger_type"), r.get("action_type")
        cfg = r.get("action_config") or {}
        problem = None
        if trig not in EVENT_TYPES:
            problem = f"Unknown trigger “{trig}”."
        elif act not in ("prompt", "webhook"):
            problem = f"Unknown action “{act}”."
        elif act == "prompt" and not cfg.get("prompt"):
            problem = "The prompt action has no prompt."
        elif act == "webhook" and not str(cfg.get("url") or "").startswith(("http://", "https://")):
            problem = "The webhook action has no valid URL."
        perms = [f"runs when “{trig}” happens"]
        if act == "webhook":
            perms.append(f"sends event data to {cfg.get('url')}")
        elif act == "prompt":
            perms.append("sends a prompt to a model and saves the reply")
        out.append({"kind": "automation_rule", "index": i, "name": name,
                    "detail": f"{trig} → {act}", "duplicate": name.lower() in have_ru, "problem": problem,
                    "permissions": perms, "added_disabled": True})

    return {"name": pack.get("name") or "Untitled pack", "description": pack.get("description") or "",
            "items": out, "importable": sum(1 for x in out if not x["problem"] and not x["duplicate"])}


def import_pack(pack: Any, include: list[str] | None = None) -> dict:
    """Add the chosen items (keys "kind:index"; default: everything that's
    valid and new). Automation rules arrive turned off so nothing fires
    until the user switches it on."""
    from app.db import storage
    from app.services import persona_service

    prev = preview_pack(pack)
    items = pack["items"]
    want = set(include) if include is not None else None
    added = {"quick_actions": 0, "personas": 0, "automation_rules": 0}
    skipped = 0
    for it in prev["items"]:
        key = f"{it['kind']}:{it['index']}"
        if it["problem"] or it["duplicate"] or (want is not None and key not in want):
            skipped += 1
            continue
        if it["kind"] == "quick_action":
            q = items["quick_actions"][it["index"]]
            storage.create_quick_action(str(q["name"]).strip()[:100], str(q["prompt_template"]).strip()[:5000], bool(q.get("auto_send")))
            added["quick_actions"] += 1
        elif it["kind"] == "persona":
            p = items["personas"][it["index"]]
            persona_service.create_persona(str(p["name"]).strip()[:80], str(p["system_prompt"]).strip()[:8000], p.get("icon"))
            added["personas"] += 1
        else:
            r = items["automation_rules"][it["index"]]
            row = storage.create_automation_rule(str(r["name"]).strip()[:100], r["trigger_type"], r.get("trigger_config") or {},
                                                 r["action_type"], r.get("action_config") or {})
            storage.set_automation_rule_enabled(row["id"], False)
            added["automation_rules"] += 1
    return {"added": added, "skipped": skipped}
