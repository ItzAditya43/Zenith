"""Lightweight ordered migration runner.

Keeps `zenith.db` upgradeable across versions without dropping data. Each
migration is a tuple `(version, name, callable)` where the callable takes
a `sqlite3.Connection` and applies forward-only changes.

The first time this runs, the baseline migration records the original
schema so even pre-migration databases upgrade cleanly.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

from app.core.config import db_path as _db_path
from app.core.logging import get_logger

log = get_logger(__name__)


def _baseline(conn: sqlite3.Connection) -> None:
    """Captures the original conversations/messages schema. Idempotent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT,
            route_role TEXT,
            route_reason TEXT,
            attachments TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
        """
    )


def _attachments_table(conn: sqlite3.Connection) -> None:
    """Persist upload metadata so it survives backend restarts."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            mime_type TEXT,
            size INTEGER NOT NULL,
            kind TEXT NOT NULL,
            conversation_id TEXT,
            message_id TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attachments_conversation
            ON attachments(conversation_id);
        """
    )


def _fts5_index(conn: sqlite3.Connection) -> None:
    """SQLite FTS5 virtual table over message content for fast
    sidebar search. The Python `sqlite3` module doesn't always have FTS5
    compiled in (e.g. some slim distros), so we probe first; if it's
    missing we record the migration as applied but skip the index — the
    search route falls back to a LIKE scan in that case."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
            "content, content_rowid='rowid', tokenize='unicode61')"
        )
    except sqlite3.OperationalError as exc:
        log.warning("migration.fts5_unavailable", error=str(exc))
        # Tag the schema with a row that lets the app know FTS5 is off.
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('fts5_available', '0')"
            )
        except Exception:
            pass
        return
    # Record the success so the app can take the FTS path confidently.
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('fts5_available', '1')"
        )
    except Exception:
        pass
    # Triggers: separate execute calls so a single failure doesn't
    # abort the whole migration. The triggers are pure indexing glue.
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
        END;"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
            DELETE FROM messages_fts WHERE rowid = old.rowid;
        END;"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
            DELETE FROM messages_fts WHERE rowid = old.rowid;
            INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
        END;"""
    )


def _memories_table(conn: sqlite3.Connection) -> None:
    """Long-term user memory: small, durable facts extracted from chats
    ("prefers metric units", "works on a project called zenith") that get
    injected into the system prompt of every turn."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'fact',
            source_conversation_id TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_content
            ON memories(content);
        """
    )


def _tool_calls_table(conn: sqlite3.Connection) -> None:
    """Full audit trail for agent tool use: every bash/file/web call the
    model makes, its args, approval status, and result. Nothing the agent
    does is invisible — this table is what backs the Settings audit log
    and the inline tool-call cards in the chat transcript."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tool_calls (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            tool TEXT NOT NULL,
            args TEXT NOT NULL,
            risk TEXT NOT NULL DEFAULT 'safe',
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT,
            created_at REAL NOT NULL,
            resolved_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_tool_calls_conversation
            ON tool_calls(conversation_id);
        """
    )


def _personas_table(conn: sqlite3.Connection) -> None:
    """Named, switchable system-prompt presets ("coding buddy", "blunt
    editor") — an alternative to the one global system prompt. A
    conversation with persona_id set uses that persona's prompt instead
    of the global one."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS personas (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            icon TEXT,
            system_prompt TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """
    )
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(conversations)").fetchall()]
    if "persona_id" not in cols:
        cur.execute("ALTER TABLE conversations ADD COLUMN persona_id TEXT")


def _message_branching(conn: sqlite3.Connection) -> None:
    """`parent_id` + `branch_root_id` let a conversation hold multiple
    branches: editing or regenerating a message creates a sibling under
    the same parent instead of overwriting history. `active` marks which
    sibling is currently shown in the linear view."""
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(messages)").fetchall()]
    if "parent_id" not in cols:
        cur.execute("ALTER TABLE messages ADD COLUMN parent_id TEXT")
    if "active" not in cols:
        cur.execute("ALTER TABLE messages ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_id)")


def _watched_folders_table(conn: sqlite3.Connection) -> None:
    """Folders Zenith periodically re-scans and indexes into the RAG
    store, so a notes vault or repo stays searchable without manual
    upload-per-file."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS watched_folders (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            extensions TEXT NOT NULL DEFAULT '.md,.txt,.py,.js,.ts,.json',
            enabled INTEGER NOT NULL DEFAULT 1,
            last_scanned_at REAL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS watched_files (
            path TEXT PRIMARY KEY,
            folder_id TEXT NOT NULL,
            mtime REAL NOT NULL,
            indexed_at REAL NOT NULL
        );
        """
    )


def _schedules_table(conn: sqlite3.Connection) -> None:
    """Recurring autonomous turns ("every morning, research X and
    summarize") — a lightweight interval scheduler, not full cron syntax,
    intentionally: one number (minutes) is enough for a personal tool and
    needs no parser."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schedules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'chat',
            interval_minutes INTEGER NOT NULL,
            conversation_id TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run_at REAL,
            next_run_at REAL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schedule_runs (
            id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            started_at REAL NOT NULL,
            finished_at REAL,
            status TEXT NOT NULL DEFAULT 'running',
            summary TEXT,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_runs_schedule ON schedule_runs(schedule_id);
        """
    )


def _conversation_workdir(conn: sqlite3.Connection) -> None:
    """A per-conversation working directory — agent mode's bash cwd and
    relative file paths resolve against it, the same way Claude Code
    binds to "the current repo" so you never repeat full paths."""
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(conversations)").fetchall()]
    if "workdir" not in cols:
        cur.execute("ALTER TABLE conversations ADD COLUMN workdir TEXT")


def _tool_call_diff_columns(conn: sqlite3.Connection) -> None:
    """Diff preview + one-step undo for file-editing tool calls: `diff` is
    a unified diff computed before the model's edit is applied (so the
    approval card can show exactly what will change, not just raw args),
    `previous_content`/`had_previous_file` capture what the file looked
    like beforehand so a later revert can restore it exactly (including
    deleting the file again if the edit created it)."""
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(tool_calls)").fetchall()]
    if "diff" not in cols:
        cur.execute("ALTER TABLE tool_calls ADD COLUMN diff TEXT")
    if "previous_content" not in cols:
        cur.execute("ALTER TABLE tool_calls ADD COLUMN previous_content TEXT")
    if "had_previous_file" not in cols:
        cur.execute("ALTER TABLE tool_calls ADD COLUMN had_previous_file INTEGER")


def _agent_checkpoints_table(conn: sqlite3.Connection) -> None:
    """One saved agent-loop state per conversation, for pausing/resuming a
    long run. When an agent turn hits its iteration cap without finishing,
    the loop's message history is stashed here (as JSON) so the next turn
    resumes from exactly where it stopped instead of starting cold. DB-backed
    (not in-memory) so a checkpoint survives a backend restart — that's the
    point of a checkpoint. At most one per conversation (PK)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_checkpoints (
            conversation_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            model TEXT,
            iterations_used INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        """
    )


def _skills_table(conn: sqlite3.Connection) -> None:
    """Reusable agent playbooks. Most are auto-detected: when the same
    ordered sequence of tool names recurs across agent-mode turns, the
    triggering prompt + tool sequence gets saved here so it can be
    replayed as a starting template instead of the agent (and user)
    re-deriving the same plan from scratch every time."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            signature TEXT NOT NULL,
            prompt_template TEXT NOT NULL,
            tool_sequence TEXT NOT NULL,
            source_conversation_id TEXT,
            auto_detected INTEGER NOT NULL DEFAULT 1,
            use_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_signature ON skills(signature);
        """
    )


def _projects_table(conn: sqlite3.Connection) -> None:
    """Projects group conversations that share context: a default working
    directory (agent mode's bash cwd) and a memory scope (memories tagged to
    a project only surface in that project's conversations, not globally).
    A conversation's `project_id` is nullable — most conversations stay
    unscoped, same as before this migration."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            workdir TEXT,
            created_at REAL NOT NULL
        );
        """
    )
    cur = conn.cursor()
    conv_cols = [r[1] for r in cur.execute("PRAGMA table_info(conversations)").fetchall()]
    if "project_id" not in conv_cols:
        cur.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")
    mem_cols = [r[1] for r in cur.execute("PRAGMA table_info(memories)").fetchall()]
    if "project_id" not in mem_cols:
        cur.execute("ALTER TABLE memories ADD COLUMN project_id TEXT")


def _calendar_events_table(conn: sqlite3.Connection) -> None:
    """A plain local calendar — no Google/Outlook OAuth, no external
    service. Events the agent creates from conversation ("remind me
    Tuesday at 3") land in the same table the Calendar UI reads."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            start_ts REAL NOT NULL,
            end_ts REAL,
            all_day INTEGER NOT NULL DEFAULT 0,
            source_conversation_id TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_ts);
        """
    )


def _notes_table(conn: sqlite3.Connection) -> None:
    """Keep-style quick notes — a fast scratchpad separate from chat
    history, for the stuff you don't want buried in a conversation
    thread. No folders/tags, deliberately: pin + color is the whole
    organizing model, same as the product it's modeled on."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT 'default',
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        """
    )


def _todos_table(conn: sqlite3.Connection) -> None:
    """A dedicated to-do list, distinct from Notes (freeform scratchpad)
    and Calendar (timed events) — discrete tasks with a done/not-done
    state and an optional due date."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS todos (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            due_ts REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        """
    )


def _email_flags_table(conn: sqlite3.Connection) -> None:
    """Background inbox triage: the email scanner classifies each new
    message once and, if urgent, records it here so the UI can badge it
    without re-scanning or re-asking the model. `message_id` is unique so
    a message is only ever classified once even across many scan cycles."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS email_flags (
            message_id TEXT PRIMARY KEY,
            subject TEXT,
            sender TEXT,
            reason TEXT,
            urgent INTEGER NOT NULL DEFAULT 0,
            seen INTEGER NOT NULL DEFAULT 0,
            flagged_at REAL NOT NULL
        );
        """
    )


def _research_reports_table(conn: sqlite3.Connection) -> None:
    """Deep research gets a persistent home instead of just landing in
    the chat thread — a saved report (query, synthesized answer, sources)
    you can reopen later and ask follow-ups against, in its own panel."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_reports (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            query TEXT NOT NULL,
            answer TEXT NOT NULL,
            sources TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL
        );
        """
    )


def _group_chat_column(conn: sqlite3.Connection) -> None:
    """A conversation can be bound to multiple personas at once — a
    simulated group chat. NULL/empty means "normal single-assistant
    conversation" (the default, unchanged behavior). `messages.speaker_persona_id`
    tags which persona said a given group-chat reply, for the UI to render
    each speaker distinctly."""
    cur = conn.cursor()
    conv_cols = [r[1] for r in cur.execute("PRAGMA table_info(conversations)").fetchall()]
    if "group_persona_ids" not in conv_cols:
        cur.execute("ALTER TABLE conversations ADD COLUMN group_persona_ids TEXT")
    msg_cols = [r[1] for r in cur.execute("PRAGMA table_info(messages)").fetchall()]
    if "speaker_persona_id" not in msg_cols:
        cur.execute("ALTER TABLE messages ADD COLUMN speaker_persona_id TEXT")


def _tool_calls_run_id_column(conn: sqlite3.Connection) -> None:
    """Groups every tool call made during one agent turn under a shared
    `run_id` (the user message id that triggered the run) so a whole run's
    file edits can be undone in one action, not just one file at a time."""
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(tool_calls)").fetchall()]
    if "run_id" not in cols:
        cur.execute("ALTER TABLE tool_calls ADD COLUMN run_id TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id)")


def _usage_events_table(conn: sqlite3.Connection) -> None:
    """One row per completed chat turn — model, token count (SSE token-chunk
    count, same methodology the live status-rail tok/s already uses
    client-side, just persisted server-side so it survives past one
    session), and timing. Powers the usage/diagnostics dashboard: token
    throughput and latency trends over time, not just a live snapshot."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            role TEXT,
            token_count INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL,
            first_token_ms INTEGER,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_usage_events_created ON usage_events(created_at);
        """
    )


def _conversation_pin_tags_share(conn: sqlite3.Connection) -> None:
    """Pinning, free-form tags, and shareable read-only links — all
    lightweight conversation metadata, same additive-column pattern as
    `workdir`/`project_id`. `tags` is a JSON array string (SQLite has no
    native array type); `share_token` is nullable and unique when set —
    a conversation is shareable only once a token has been issued."""
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(conversations)").fetchall()]
    if "pinned" not in cols:
        cur.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    if "tags" not in cols:
        cur.execute("ALTER TABLE conversations ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
    if "share_token" not in cols:
        cur.execute("ALTER TABLE conversations ADD COLUMN share_token TEXT")
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_share_token "
        "ON conversations(share_token) WHERE share_token IS NOT NULL"
    )


def _project_agent_mode(conn: sqlite3.Connection) -> None:
    """Per-project autonomy override — a project can pin agent_mode to
    something different from the global default (e.g. always full-auto
    in a scratch repo, always manual in dotfiles). NULL means "use the
    global agent_mode setting", same fallback as before this migration."""
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(projects)").fetchall()]
    if "agent_mode" not in cols:
        cur.execute("ALTER TABLE projects ADD COLUMN agent_mode TEXT")


def _snippets_table(conn: sqlite3.Connection) -> None:
    """Reusable prompt/message snippets — inserted into the composer,
    distinct from personas (which are system-prompt-level, applied for a
    whole conversation) since these are message-level, one-off inserts."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS snippets (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """
    )


def _mcp_servers_table(conn: sqlite3.Connection) -> None:
    """Configured MCP servers (run as local subprocesses over stdio — no
    hosted/paid MCP services involved). Each server's advertised tools
    get merged into the agent loop's tool set at runtime."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mcp_servers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            command TEXT NOT NULL,
            args TEXT NOT NULL DEFAULT '[]',
            env TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL
        );
        """
    )


# Ordered list — never reorder, only append.
MIGRATIONS: list[tuple[int, str, callable]] = [
    (1, "baseline", _baseline),
    (2, "attachments_table", _attachments_table),
    (3, "fts5_index", _fts5_index),
    (4, "memories_table", _memories_table),
    (5, "tool_calls_table", _tool_calls_table),
    (6, "personas_table", _personas_table),
    (7, "message_branching", _message_branching),
    (8, "watched_folders_table", _watched_folders_table),
    (9, "schedules_table", _schedules_table),
    (10, "mcp_servers_table", _mcp_servers_table),
    (11, "conversation_workdir", _conversation_workdir),
    (12, "tool_call_diff_columns", _tool_call_diff_columns),
    (13, "agent_checkpoints_table", _agent_checkpoints_table),
    (14, "skills_table", _skills_table),
    (15, "projects_table", _projects_table),
    (16, "calendar_events_table", _calendar_events_table),
    (17, "notes_table", _notes_table),
    (18, "todos_table", _todos_table),
    (19, "email_flags_table", _email_flags_table),
    (20, "research_reports_table", _research_reports_table),
    (21, "group_chat_column", _group_chat_column),
    (22, "tool_calls_run_id_column", _tool_calls_run_id_column),
    (23, "usage_events_table", _usage_events_table),
    (24, "conversation_pin_tags_share", _conversation_pin_tags_share),
    (25, "project_agent_mode", _project_agent_mode),
    (26, "snippets_table", _snippets_table),
]


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  applied_at REAL NOT NULL"
        ")"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"] or 0) if row else 0


def current_version(conn: sqlite3.Connection) -> int:
    """Public alias of `_current_version` so tests / external callers
    can ask the DB what schema_version it has without re-implementing."""
    return _current_version(conn)


@dataclass
class MigrationReport:
    """Outcome of one `run_migrations` call.

    `applied`  — versions that were just applied during this call.
    `skipped`  — versions that were already applied (and therefore skipped)."""
    applied: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)


def _run_migrations_on(conn: sqlite3.Connection) -> MigrationReport:
    report = MigrationReport()
    already = _current_version(conn)
    for version, name, fn in MIGRATIONS:
        if version <= already:
            report.skipped.append(version)
            continue
        log.info("migration.apply", version=version, name=name)
        fn(conn)
        conn.execute(
            "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, time.time()),
        )
        report.applied.append(version)
    conn.commit()
    return report


def run_migrations(conn: sqlite3.Connection | None = None) -> MigrationReport:
    """Apply any not-yet-applied migrations and return a report.

    When `conn` is None (the production startup path), a fresh connection
    to the default `DB_PATH` is opened and closed. Tests pass their own
    connection to share state with the rest of the suite."""
    if conn is None:
        own = sqlite3.connect(str(_db_path()))
        own.row_factory = sqlite3.Row
        try:
            return _run_migrations_on(own)
        finally:
            own.close()
    return _run_migrations_on(conn)
