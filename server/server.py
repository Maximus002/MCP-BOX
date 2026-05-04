"""
memory-mcp — MCP server for Claude-to-Claude async messaging.

Two+ Claudes on different machines exchange messages through this server:
- Each has its own identity (agent_a, agent_b, agent_c, ...)
- Messages stored as markdown files with YAML frontmatter
- Git auto-commits each write for audit/history
- Bearer-token auth, identity resolved from token
- Webhooks notify recipients on new messages (fire-and-forget)
- Optional read-only web UI for humans to browse threads
"""

from __future__ import annotations

import os
import re
import json
import base64
import hmac
import uuid
import yaml
import logging
import threading
import contextvars
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

import frontmatter
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse, HTMLResponse, Response
from starlette.routing import Route
from starlette.requests import Request

# --- paths & config ---

DATA_DIR = Path(os.environ.get("MEMORY_MCP_DATA", "/var/lib/memory-mcp/data"))
CONFIG_PATH = Path(os.environ.get("MEMORY_MCP_CONFIG", "/etc/memory-mcp/config.yaml"))
BIND_HOST = os.environ.get("MEMORY_MCP_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("MEMORY_MCP_PORT", "8765"))

MESSAGES_DIR = DATA_DIR / "messages"
SHARED_DIR = DATA_DIR / "shared"
STATE_DIR = DATA_DIR / "_state"
TASKS_FILE = SHARED_DIR / "_tasks.yaml"
PRESENCE_FILE = STATE_DIR / "presence.json"

for d in (MESSAGES_DIR, SHARED_DIR, STATE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# --- load config ---

if not CONFIG_PATH.exists():
    raise SystemExit(f"config file not found: {CONFIG_PATH}")

with open(CONFIG_PATH) as f:
    _config = yaml.safe_load(f) or {}

TOKENS: dict[str, dict] = _config.get("tokens", {})
if not TOKENS:
    raise SystemExit("no tokens defined in config")

IDENTITIES = {entry["identity"] for entry in TOKENS.values()}

WEBHOOKS: dict[str, str] = (_config.get("webhooks") or {})
WEBHOOK_SECRET: str = (_config.get("webhook_secret") or "").strip()

# ui_users: {username: password} for HTTP Basic on /ui. Empty = UI disabled.
UI_USERS: dict[str, str] = (_config.get("ui_users") or {})

# default TTL for auto-archive of read [fyi] messages
AUTO_ARCHIVE_TTL_DAYS = int(_config.get("auto_archive_ttl_days") or 14)

ALLOWED_MESSAGE_TYPES = {
    "prose", "scan_result", "config_diff", "task_update", "ack",
}

# --- webhook dispatch ---

_webhook_log = logging.getLogger("memory-mcp.webhook")


def _fire_webhook(recipient: str, payload: dict) -> None:
    url = WEBHOOKS.get(recipient)
    if not url:
        return

    def _send():
        try:
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if WEBHOOK_SECRET:
                headers["X-MemoryMCP-Secret"] = WEBHOOK_SECRET
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=3) as resp:
                _webhook_log.info("webhook %s -> %s: %s", recipient, url, resp.status)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            _webhook_log.warning("webhook %s -> %s failed: %s", recipient, url, e)

    threading.Thread(target=_send, daemon=True).start()

# --- request-scoped identity ---

_current_identity: contextvars.ContextVar[str] = contextvars.ContextVar("identity")


def me() -> str:
    try:
        return _current_identity.get()
    except LookupError:
        raise RuntimeError("identity not set; auth middleware missing?")


# --- git helpers ---

def _git(*args: str, cwd: Path = DATA_DIR) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def _git_init_if_needed() -> None:
    if not (DATA_DIR / ".git").exists():
        _git("init", "-q", "-b", "main")
        _git("config", "user.email", "memory-mcp@localhost")
        _git("config", "user.name", "memory-mcp")
        (DATA_DIR / ".gitkeep").touch()
        _git("add", ".gitkeep")
        _git("commit", "-q", "-m", "init")


def _git_commit(message: str, paths: list[Path]) -> None:
    rels = [str(p.relative_to(DATA_DIR)) for p in paths if p.exists()]
    if not rels:
        return
    _git("add", *rels)
    _git("commit", "-q", "-m", message, "--allow-empty")


_git_init_if_needed()

# --- helpers ---

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


def _msg_path(thread_id: str, filename: str) -> Path:
    return MESSAGES_DIR / thread_id / filename


def _slug(s: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:maxlen] or "untitled"


def _load_msg(path: Path) -> dict:
    post = frontmatter.load(path)
    meta = dict(post.metadata)
    meta["body"] = post.content
    meta["_path"] = str(path)
    # backward-compat defaults
    meta.setdefault("reactions", {})
    meta.setdefault("archived", False)
    meta.setdefault("message_type", "prose")
    meta.setdefault("payload", None)
    meta.setdefault("encrypted", None)
    return meta


def _save_msg(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, **meta)
    with open(path, "wb") as f:
        frontmatter.dump(post, f)


def _iter_messages():
    """Yield all message dicts across all threads."""
    if not MESSAGES_DIR.exists():
        return
    for thread_dir in sorted(MESSAGES_DIR.iterdir()):
        if not thread_dir.is_dir():
            continue
        for msg_file in sorted(thread_dir.glob("*.md")):
            yield _load_msg(msg_file)


def _find_msg(message_id: str) -> Optional[dict]:
    for msg in _iter_messages():
        if msg.get("id") == message_id:
            return msg
    return None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# --- presence tracking ---

_presence_lock = threading.Lock()


def _load_presence() -> dict:
    if not PRESENCE_FILE.exists():
        return {}
    try:
        return json.loads(PRESENCE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_presence(data: dict) -> None:
    PRESENCE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _touch_presence(identity: str, action: str) -> None:
    """Record that identity performed action now. Fields: last_inbox, last_read, last_send."""
    with _presence_lock:
        data = _load_presence()
        entry = data.setdefault(identity, {})
        ts = _now_iso()
        entry[f"last_{action}"] = ts
        entry["last_seen"] = ts
        _save_presence(data)


# --- MCP server ---

mcp = FastMCP(
    name="memory-mcp",
    instructions=(
        "Async message exchange between Claude identities. "
        "Each caller has its own identity (resolved from auth token). "
        "Core: whoami, send, inbox, read, thread, outbox, search, list_peers, presence. "
        "Reactions: react (emoji ack without spawning a reply). "
        "Archive: archive / archive_expired (prune read [fyi]). "
        "Shared board: post_shared_note, read_shared_note, list_shared_notes. "
        "Joint TODO: tasks_list, task_add, task_update. "
        "Replies: always reuse thread_id + reply_to of the message you're answering."
    ),
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def whoami() -> dict:
    """Return this Claude's identity on the memory-mcp bus."""
    identity = me()
    display = next(
        (v["display"] for v in TOKENS.values() if v["identity"] == identity), identity
    )
    return {"identity": identity, "display": display, "peers": sorted(IDENTITIES - {identity})}


@mcp.tool()
def list_peers() -> list[dict]:
    """List all known identities and when each last sent/read messages (from message history)."""
    last_sent: dict[str, str] = {}
    last_read: dict[str, str] = {}
    for msg in _iter_messages():
        f = msg.get("from")
        if f and (f not in last_sent or msg["timestamp"] > last_sent[f]):
            last_sent[f] = msg["timestamp"]
        for reader in msg.get("read_by", []) or []:
            if reader not in last_read or msg["timestamp"] > last_read[reader]:
                last_read[reader] = msg["timestamp"]
    return [
        {"identity": ident, "last_sent": last_sent.get(ident), "last_read": last_read.get(ident)}
        for ident in sorted(IDENTITIES)
    ]


@mcp.tool()
def presence(stale_after_minutes: int = 60) -> list[dict]:
    """
    Liveness view of each identity.

    For every known identity, reports when it last called inbox/read/send
    (from server-side presence log) and flags it `stale` if no activity
    within `stale_after_minutes`. Use to decide whether a peer is likely
    around right now before sending an urgent question.
    """
    data = _load_presence()
    threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)
    out = []
    for ident in sorted(IDENTITIES):
        entry = data.get(ident, {}) or {}
        last_seen = _parse_iso(entry.get("last_seen"))
        stale = True
        if last_seen is not None:
            stale = last_seen < threshold
        out.append({
            "identity": ident,
            "last_seen": entry.get("last_seen"),
            "last_inbox": entry.get("last_inbox"),
            "last_read": entry.get("last_read"),
            "last_send": entry.get("last_send"),
            "stale": stale,
        })
    return out


@mcp.tool()
def send(
    to: str,
    subject: str,
    body: str,
    thread_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    reply_to: Optional[str] = None,
    message_type: str = "prose",
    payload: Optional[dict] = None,
    encrypted: Optional[str] = None,
) -> dict:
    """
    Send a message to another identity.

    Args:
        to: recipient identity (e.g. "agent_b")
        subject: short subject line
        body: message body in markdown (prose) or the encrypted blob itself
        thread_id: existing thread to continue; omit to start new thread
        tags: optional list of tags for filtering
        reply_to: optional message id this replies to
        message_type: "prose" (default), "scan_result", "config_diff",
            "task_update", or "ack". Typed messages may also carry `payload`.
        payload: optional structured data (dict) — complements body.
            Other side can parse without text scraping.
        encrypted: mark the body as an encrypted blob. Use "age" when body is
            an age-armored ciphertext. Server never sees plaintext; the flag
            only helps the recipient's UI (no preview, decrypt hint).

    Returns: {message_id, thread_id, path}
    """
    sender = me()
    if to not in IDENTITIES:
        raise ValueError(f"unknown recipient: {to}. known: {sorted(IDENTITIES)}")
    if to == sender:
        raise ValueError("cannot send to self")
    if message_type not in ALLOWED_MESSAGE_TYPES:
        raise ValueError(
            f"unknown message_type: {message_type}. allowed: {sorted(ALLOWED_MESSAGE_TYPES)}"
        )
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    if encrypted is not None:
        if encrypted != "age":
            raise ValueError(f"unsupported encrypted scheme: {encrypted}")
        if "-----BEGIN AGE ENCRYPTED FILE-----" not in body:
            raise ValueError(
                "encrypted=age requires body to contain an age armored blob "
                "('-----BEGIN AGE ENCRYPTED FILE-----' marker)"
            )

    msg_id = f"msg_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_short_id()}"
    if not thread_id:
        thread_id = f"thread_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{_slug(subject, 20)}_{_short_id()}"

    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{sender}-{_short_id()}.md"
    path = _msg_path(thread_id, filename)

    meta = {
        "id": msg_id,
        "from": sender,
        "to": to,
        "subject": subject,
        "thread_id": thread_id,
        "timestamp": _now_iso(),
        "tags": tags or [],
        "reply_to": reply_to,
        "read_by": [sender],
        "reactions": {},
        "archived": False,
        "message_type": message_type,
        "payload": payload,
        "encrypted": encrypted,
    }

    _save_msg(path, meta, body)
    _git_commit(f"send: {sender} → {to}: {subject}", [path])
    _touch_presence(sender, "send")

    _fire_webhook(to, {
        "event": "message",
        "to": to,
        "from": sender,
        "subject": subject,
        "message_id": msg_id,
        "thread_id": thread_id,
    })

    return {"message_id": msg_id, "thread_id": thread_id, "path": str(path.relative_to(DATA_DIR))}


def _msg_preview(msg: dict, n: int = 200) -> str:
    if msg.get("encrypted") == "age":
        return "<encrypted:age>"
    body = msg.get("body", "") or ""
    return body[:n] + ("..." if len(body) > n else "")


def _summary(msg: dict, identity: Optional[str] = None) -> dict:
    out = {
        "id": msg["id"],
        "from": msg["from"],
        "to": msg["to"],
        "subject": msg["subject"],
        "thread_id": msg["thread_id"],
        "timestamp": msg["timestamp"],
        "tags": msg.get("tags") or [],
        "message_type": msg.get("message_type") or "prose",
        "encrypted": msg.get("encrypted"),
        "archived": bool(msg.get("archived")),
        "reactions": msg.get("reactions") or {},
        "preview": _msg_preview(msg),
    }
    if identity is not None:
        out["read"] = identity in (msg.get("read_by") or [])
    return out


@mcp.tool()
def inbox(unread_only: bool = True, limit: int = 20, include_archived: bool = False) -> list[dict]:
    """
    List incoming messages addressed to this identity (newest first).

    Args:
        unread_only: if True, only messages not yet read by you
        limit: max count
        include_archived: include archived messages
    """
    identity = me()
    _touch_presence(identity, "inbox")
    results = []
    for msg in _iter_messages():
        if msg.get("to") != identity:
            continue
        if unread_only and identity in (msg.get("read_by") or []):
            continue
        if not include_archived and msg.get("archived"):
            continue
        results.append(_summary(msg, identity))
    results.sort(key=lambda m: m["timestamp"], reverse=True)
    return results[:limit]


@mcp.tool()
def read(message_id: str) -> dict:
    """
    Read a specific message by its id. Marks it as read for you.
    Returns full body plus all metadata (reactions, type, payload, encryption flag).
    """
    identity = me()
    msg = _find_msg(message_id)
    if msg is None:
        raise ValueError(f"message not found: {message_id}")

    read_by = list(msg.get("read_by") or [])
    was_unread = identity not in read_by
    if was_unread:
        read_by.append(identity)
        path = Path(msg["_path"])
        body = msg.pop("body")
        msg.pop("_path")
        msg["read_by"] = read_by
        _save_msg(path, msg, body)
        _git_commit(f"read: {identity} → {message_id}", [path])
        msg["body"] = body
    else:
        msg["body"] = msg.pop("body")
        msg.pop("_path")

    _touch_presence(identity, "read")
    return msg


@mcp.tool()
def outbox(limit: int = 20, include_archived: bool = False) -> list[dict]:
    """List messages this identity has sent (newest first)."""
    identity = me()
    results = []
    for msg in _iter_messages():
        if msg.get("from") != identity:
            continue
        if not include_archived and msg.get("archived"):
            continue
        s = _summary(msg)
        s["read_by_recipient"] = msg["to"] in (msg.get("read_by") or [])
        results.append(s)
    results.sort(key=lambda m: m["timestamp"], reverse=True)
    return results[:limit]


@mcp.tool()
def thread(thread_id: str, include_archived: bool = True) -> list[dict]:
    """Return all messages in a thread, chronologically."""
    results = []
    thread_dir = MESSAGES_DIR / thread_id
    if not thread_dir.exists():
        raise ValueError(f"thread not found: {thread_id}")
    for msg_file in sorted(thread_dir.glob("*.md")):
        msg = _load_msg(msg_file)
        if not include_archived and msg.get("archived"):
            continue
        msg.pop("_path", None)
        results.append(msg)
    return results


@mcp.tool()
def search(
    query: Optional[str] = None,
    scope: str = "all",
    tags: Optional[list[str]] = None,
    from_: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    regex: bool = False,
    include_archived: bool = False,
    limit: int = 20,
) -> list[dict]:
    """
    Search across messages with combinable filters.

    Args:
        query: substring (or regex if regex=True) matched against subject + body.
            Omit to filter purely by metadata.
        scope: "all" | "inbox" | "outbox"
        tags: require ALL of these tags on the message
        from_: filter by sender identity
        since: ISO8601 timestamp — only messages at or after
        until: ISO8601 timestamp — only messages at or before
        regex: treat `query` as a regex (case-insensitive)
        include_archived: include archived messages (default: off)
        limit: max results
    """
    identity = me()
    pat = None
    if query:
        if regex:
            try:
                pat = re.compile(query, re.IGNORECASE | re.MULTILINE)
            except re.error as e:
                raise ValueError(f"bad regex: {e}")
        else:
            q = query.lower()
    since_dt = _parse_iso(since)
    until_dt = _parse_iso(until)
    want_tags = set(tags or [])
    results = []
    for msg in _iter_messages():
        if scope == "inbox" and msg.get("to") != identity:
            continue
        if scope == "outbox" and msg.get("from") != identity:
            continue
        if from_ and msg.get("from") != from_:
            continue
        if not include_archived and msg.get("archived"):
            continue
        if want_tags and not want_tags.issubset(set(msg.get("tags") or [])):
            continue
        ts = _parse_iso(msg.get("timestamp"))
        if since_dt and (ts is None or ts < since_dt):
            continue
        if until_dt and (ts is None or ts > until_dt):
            continue
        if query:
            hay = (msg.get("subject", "") + "\n" + (msg.get("body") or ""))
            if pat is not None:
                if not pat.search(hay):
                    continue
            else:
                if q not in hay.lower():
                    continue
        results.append(_summary(msg, identity))
    results.sort(key=lambda m: m["timestamp"], reverse=True)
    return results[:limit]


# --- reactions ---

ALLOWED_REACTIONS = {"👍", "👎", "✅", "❌", "🤔", "👀", "🎉", "⚠️", "🙏", "🚀"}


@mcp.tool()
def react(message_id: str, emoji: str) -> dict:
    """
    Attach an emoji reaction to a message — lightweight ack without polluting
    the thread with a full reply. Replaces your previous reaction on this
    message. Pass empty string to remove.

    Allowed: 👍 👎 ✅ ❌ 🤔 👀 🎉 ⚠️ 🙏 🚀
    """
    identity = me()
    if emoji and emoji not in ALLOWED_REACTIONS:
        raise ValueError(
            f"reaction not allowed: {emoji!r}. allowed: {' '.join(sorted(ALLOWED_REACTIONS))}"
        )
    msg = _find_msg(message_id)
    if msg is None:
        raise ValueError(f"message not found: {message_id}")
    reactions = dict(msg.get("reactions") or {})
    if emoji:
        reactions[identity] = emoji
    else:
        reactions.pop(identity, None)
    path = Path(msg["_path"])
    body = msg.pop("body")
    msg.pop("_path")
    msg["reactions"] = reactions
    _save_msg(path, msg, body)
    _git_commit(f"react: {identity} {emoji or '(cleared)'} → {message_id}", [path])
    return {"message_id": message_id, "reactions": reactions}


# --- archive ---

@mcp.tool()
def archive(message_id: str) -> dict:
    """
    Mark a single message as archived. Archived messages hide from `inbox`
    and `outbox` by default (pass include_archived=True to see them).
    """
    identity = me()
    msg = _find_msg(message_id)
    if msg is None:
        raise ValueError(f"message not found: {message_id}")
    if msg.get("from") != identity and msg.get("to") != identity:
        raise ValueError("can only archive messages you sent or received")
    if msg.get("archived"):
        return {"message_id": message_id, "archived": True, "already": True}
    path = Path(msg["_path"])
    body = msg.pop("body")
    msg.pop("_path")
    msg["archived"] = True
    msg["archived_at"] = _now_iso()
    msg["archived_by"] = identity
    _save_msg(path, msg, body)
    _git_commit(f"archive: {identity} → {message_id}", [path])
    return {"message_id": message_id, "archived": True}


@mcp.tool()
def archive_expired(ttl_days: Optional[int] = None, dry_run: bool = True) -> dict:
    """
    Bulk-archive read [fyi]-tagged messages older than `ttl_days` (default
    from config, currently {ttl}).

    Criteria (all must hold):
    - `fyi` is in tags
    - `archived` is False
    - read by both sender and recipient
    - timestamp older than cutoff

    dry_run=True returns the list without touching anything.
    """.replace("{ttl}", str(AUTO_ARCHIVE_TTL_DAYS))
    ttl = ttl_days if ttl_days is not None else AUTO_ARCHIVE_TTL_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl)
    candidates = []
    for msg in _iter_messages():
        if msg.get("archived"):
            continue
        if "fyi" not in (msg.get("tags") or []):
            continue
        read_by = set(msg.get("read_by") or [])
        if not ({msg.get("from"), msg.get("to")} <= read_by):
            continue
        ts = _parse_iso(msg.get("timestamp"))
        if ts is None or ts >= cutoff:
            continue
        candidates.append(msg)

    if dry_run:
        return {
            "ttl_days": ttl,
            "would_archive": [
                {"id": m["id"], "subject": m["subject"], "timestamp": m["timestamp"]}
                for m in candidates
            ],
        }

    archived_ids = []
    for msg in candidates:
        path = Path(msg["_path"])
        body = msg.pop("body")
        msg.pop("_path")
        msg["archived"] = True
        msg["archived_at"] = _now_iso()
        msg["archived_by"] = "system:ttl"
        _save_msg(path, msg, body)
        archived_ids.append(msg["id"])
    if archived_ids:
        paths = [Path(m["_path"]) if "_path" in m else MESSAGES_DIR for m in candidates]
        # recompute paths since _path was popped
        paths = []
        for mid in archived_ids:
            m = _find_msg(mid)
            if m:
                paths.append(Path(m["_path"]))
        _git_commit(f"archive: ttl sweep ({len(archived_ids)} msgs)", paths)
    return {"ttl_days": ttl, "archived": archived_ids}


# --- shared notes ---

@mcp.tool()
def post_shared_note(name: str, content: str) -> dict:
    """
    Write to the shared notes board (facts both identities agree on:
    network topology, static configs, etc.). Overwrites if exists.
    """
    identity = me()
    slug = _slug(name)
    if slug.startswith("_"):
        raise ValueError("note name must not start with underscore (reserved)")
    path = SHARED_DIR / f"{slug}.md"
    header = f"<!-- last edited by {identity} at {_now_iso()} -->\n\n"
    path.write_text(header + content)
    _git_commit(f"shared: {identity} updated {name}", [path])
    return {"name": name, "path": str(path.relative_to(DATA_DIR))}


@mcp.tool()
def read_shared_note(name: str) -> dict:
    """Read a shared note by name."""
    path = SHARED_DIR / f"{_slug(name)}.md"
    if not path.exists():
        raise ValueError(f"shared note not found: {name}")
    return {"name": name, "content": path.read_text()}


@mcp.tool()
def list_shared_notes() -> list[str]:
    """List all shared notes by name."""
    return sorted(p.stem for p in SHARED_DIR.glob("*.md") if not p.stem.startswith("_"))


# --- shared tasks (joint TODO board) ---

_tasks_lock = threading.Lock()
ALLOWED_TASK_STATUSES = {"open", "in_progress", "blocked", "done", "dropped"}


def _load_tasks() -> dict:
    if not TASKS_FILE.exists():
        return {"tasks": []}
    try:
        data = yaml.safe_load(TASKS_FILE.read_text()) or {"tasks": []}
    except yaml.YAMLError:
        return {"tasks": []}
    data.setdefault("tasks", [])
    return data


def _save_tasks(data: dict) -> None:
    TASKS_FILE.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


@mcp.tool()
def tasks_list(status: Optional[str] = None, owner: Optional[str] = None) -> list[dict]:
    """
    List joint TODO items shared between identities. Optional filters by
    status ("open"/"in_progress"/"blocked"/"done"/"dropped") or owner.
    """
    data = _load_tasks()
    out = []
    for t in data.get("tasks", []):
        if status and t.get("status") != status:
            continue
        if owner and t.get("owner") != owner:
            continue
        out.append(t)
    out.sort(key=lambda t: (t.get("status") == "done", t.get("updated", "")), reverse=False)
    return out


@mcp.tool()
def task_add(title: str, owner: Optional[str] = None, notes: str = "",
             tags: Optional[list[str]] = None) -> dict:
    """
    Add a new task to the shared board.

    Args:
        title: short task title
        owner: identity responsible (omit for unassigned)
        notes: longer free-form description
        tags: optional tags for filtering
    """
    identity = me()
    if owner and owner not in IDENTITIES:
        raise ValueError(f"unknown owner: {owner}")
    with _tasks_lock:
        data = _load_tasks()
        task = {
            "id": f"task_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_short_id()}",
            "title": title,
            "owner": owner,
            "status": "open",
            "notes": notes,
            "tags": tags or [],
            "created_by": identity,
            "created": _now_iso(),
            "updated": _now_iso(),
            "history": [{"ts": _now_iso(), "by": identity, "action": "created"}],
        }
        data["tasks"].append(task)
        _save_tasks(data)
        _git_commit(f"task: {identity} added {task['id']}: {title}", [TASKS_FILE])
        return task


@mcp.tool()
def task_update(task_id: str, status: Optional[str] = None,
                owner: Optional[str] = None, notes: Optional[str] = None,
                title: Optional[str] = None) -> dict:
    """
    Update an existing task. Only the fields you pass are changed. Each
    update appends an entry to the task's history.

    status: "open" | "in_progress" | "blocked" | "done" | "dropped"
    owner:  identity name, or "" to clear
    """
    identity = me()
    if status is not None and status not in ALLOWED_TASK_STATUSES:
        raise ValueError(
            f"bad status: {status}. allowed: {sorted(ALLOWED_TASK_STATUSES)}"
        )
    if owner is not None and owner != "" and owner not in IDENTITIES:
        raise ValueError(f"unknown owner: {owner}")
    with _tasks_lock:
        data = _load_tasks()
        for t in data.get("tasks", []):
            if t.get("id") == task_id:
                changes = {}
                if status is not None and t.get("status") != status:
                    changes["status"] = status
                if owner is not None:
                    new_owner = owner or None
                    if t.get("owner") != new_owner:
                        changes["owner"] = new_owner
                if notes is not None and t.get("notes") != notes:
                    changes["notes"] = notes
                if title is not None and t.get("title") != title:
                    changes["title"] = title
                if not changes:
                    return t
                t.update(changes)
                t["updated"] = _now_iso()
                t.setdefault("history", []).append({
                    "ts": _now_iso(), "by": identity, "action": "updated",
                    "changes": list(changes.keys()),
                })
                _save_tasks(data)
                _git_commit(
                    f"task: {identity} updated {task_id} ({', '.join(changes.keys())})",
                    [TASKS_FILE],
                )
                return t
        raise ValueError(f"task not found: {task_id}")


# --- auth middleware (MCP + UI) ---

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # health — no auth
        if path in ("/health", "/healthz"):
            return await call_next(request)

        # UI routes — HTTP Basic
        if path == "/ui" or path.startswith("/ui/"):
            if not UI_USERS:
                return PlainTextResponse("UI disabled (no ui_users in config)", status_code=404)
            auth = request.headers.get("authorization", "")
            if not auth.lower().startswith("basic "):
                return Response(
                    "auth required", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="memory-mcp"'},
                )
            try:
                decoded = base64.b64decode(auth[6:].strip()).decode("utf-8", errors="replace")
                user, _, pw = decoded.partition(":")
            except Exception:
                return Response("bad auth", status_code=400)
            expected = UI_USERS.get(user)
            if not expected or not hmac.compare_digest(str(expected), pw):
                return Response(
                    "forbidden", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="memory-mcp"'},
                )
            request.state.ui_user = user
            return await call_next(request)

        # MCP routes — Bearer
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return JSONResponse({"error": "missing bearer token"}, status_code=401)
        token = auth[7:].strip()
        if token not in TOKENS:
            return JSONResponse({"error": "invalid token"}, status_code=401)
        identity = TOKENS[token]["identity"]
        token_ctx = _current_identity.set(identity)
        try:
            response = await call_next(request)
        finally:
            _current_identity.reset(token_ctx)
        return response


# --- read-only web UI ---

def _esc(s: Any) -> str:
    import html
    return html.escape("" if s is None else str(s))


def _ui_page(title: str, body_html: str) -> HTMLResponse:
    html_doc = f"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — memory-mcp</title>
<style>
  body {{ font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 0; padding: 0; background: #0f1113; color: #d8dbe0; }}
  header {{ background: #181a1e; border-bottom: 1px solid #2a2e35; padding: 10px 20px; }}
  header a {{ color: #9ecbff; text-decoration: none; margin-right: 16px; font-weight: 500; }}
  header a:hover {{ text-decoration: underline; }}
  main {{ max-width: 960px; margin: 0 auto; padding: 20px; }}
  h1 {{ font-size: 20px; margin: 0 0 16px; }}
  h2 {{ font-size: 16px; margin: 24px 0 10px; color: #b7bdc6; border-bottom: 1px solid #2a2e35; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  td, th {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #23262c; vertical-align: top; }}
  th {{ color: #8a8f99; font-weight: 500; }}
  tr:hover td {{ background: #15171b; }}
  a {{ color: #9ecbff; }}
  .tag {{ display: inline-block; background: #23262c; padding: 1px 6px; border-radius: 10px;
         font-size: 11px; color: #b7bdc6; margin-right: 4px; }}
  .muted {{ color: #6b7280; }}
  .badge-unread {{ background: #2d5ff0; color: white; padding: 1px 6px; border-radius: 10px; font-size: 11px; }}
  .badge-stale {{ background: #6b7280; color: white; padding: 1px 6px; border-radius: 10px; font-size: 11px; }}
  .badge-live {{ background: #2d9a3a; color: white; padding: 1px 6px; border-radius: 10px; font-size: 11px; }}
  pre {{ background: #181a1e; border: 1px solid #2a2e35; padding: 10px; overflow: auto;
         border-radius: 4px; }}
  .msg {{ background: #13151a; border: 1px solid #2a2e35; border-radius: 6px;
          padding: 12px 16px; margin-bottom: 12px; }}
  .msg-head {{ font-size: 13px; color: #8a8f99; margin-bottom: 6px; }}
  .msg-body {{ white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
               font-size: 13px; }}
  .reactions {{ display: inline-block; margin-left: 6px; color: #b7bdc6; }}
  form.search {{ margin: 12px 0; }}
  input[type=text], input[type=search] {{ background: #181a1e; border: 1px solid #2a2e35;
    color: #d8dbe0; padding: 6px 10px; border-radius: 4px; width: 300px; }}
  button {{ background: #2d5ff0; border: none; color: white; padding: 6px 14px;
            border-radius: 4px; cursor: pointer; }}
  .arch {{ opacity: 0.5; }}
  .status-open {{ color: #ffd27a; }}
  .status-in_progress {{ color: #9ecbff; }}
  .status-blocked {{ color: #ff8080; }}
  .status-done {{ color: #7acc7a; }}
  .status-dropped {{ color: #6b7280; text-decoration: line-through; }}
</style>
</head><body>
<header>
  <a href="/ui">Главная</a>
  <a href="/ui/threads">Треды</a>
  <a href="/ui/notes">Shared&nbsp;notes</a>
  <a href="/ui/tasks">Tasks</a>
  <a href="/ui/search">Поиск</a>
</header>
<main>
{body_html}
</main>
</body></html>"""
    return HTMLResponse(html_doc)


def _collect_threads(include_archived: bool = False) -> list[dict]:
    """One row per thread: last timestamp, participants, message count, last subject."""
    threads: dict[str, dict] = {}
    for msg in _iter_messages():
        if not include_archived and msg.get("archived"):
            continue
        tid = msg["thread_id"]
        t = threads.setdefault(tid, {
            "thread_id": tid,
            "count": 0,
            "participants": set(),
            "tags": set(),
            "last_ts": "",
            "last_subject": "",
            "has_unread": set(),
        })
        t["count"] += 1
        t["participants"].add(msg.get("from"))
        t["participants"].add(msg.get("to"))
        for tag in msg.get("tags") or []:
            t["tags"].add(tag)
        ts = msg["timestamp"]
        if ts > t["last_ts"]:
            t["last_ts"] = ts
            t["last_subject"] = msg["subject"]
        # Track which identities haven't read this msg (for unread badge)
        read_by = set(msg.get("read_by") or [])
        for ident in [msg.get("from"), msg.get("to")]:
            if ident and ident not in read_by:
                t["has_unread"].add(ident)
    out = list(threads.values())
    out.sort(key=lambda t: t["last_ts"], reverse=True)
    for t in out:
        t["participants"] = sorted(x for x in t["participants"] if x)
        t["tags"] = sorted(t["tags"])
        t["has_unread"] = sorted(t["has_unread"])
    return out


async def ui_index(request: Request) -> Response:
    threads = _collect_threads()[:20]
    presence_data = _load_presence()
    threshold = datetime.now(timezone.utc) - timedelta(minutes=60)

    rows_p = []
    for ident in sorted(IDENTITIES):
        entry = presence_data.get(ident, {}) or {}
        last_seen = _parse_iso(entry.get("last_seen"))
        stale = last_seen is None or last_seen < threshold
        badge = '<span class="badge-stale">stale</span>' if stale else '<span class="badge-live">live</span>'
        rows_p.append(
            f"<tr><td>{_esc(ident)}</td>"
            f"<td>{badge}</td>"
            f"<td class='muted'>{_esc(entry.get('last_seen') or '—')}</td>"
            f"<td class='muted'>inbox: {_esc(entry.get('last_inbox') or '—')}</td>"
            f"<td class='muted'>send: {_esc(entry.get('last_send') or '—')}</td>"
            f"</tr>"
        )
    presence_html = (
        "<h2>Присутствие</h2>"
        "<table><tr><th>identity</th><th></th><th>last seen</th>"
        "<th>last inbox</th><th>last send</th></tr>"
        + "".join(rows_p) + "</table>"
    )

    rows_t = []
    for t in threads:
        unread = ""
        if t["has_unread"]:
            unread = f" <span class='badge-unread'>unread: {_esc(','.join(t['has_unread']))}</span>"
        tags = "".join(f"<span class='tag'>{_esc(x)}</span>" for x in t["tags"])
        rows_t.append(
            f"<tr><td class='muted'>{_esc(t['last_ts'][:16].replace('T',' '))}</td>"
            f"<td><a href='/ui/thread/{_esc(t['thread_id'])}'>{_esc(t['last_subject'])}</a>{unread}</td>"
            f"<td class='muted'>{_esc(', '.join(t['participants']))}</td>"
            f"<td>{tags}</td>"
            f"<td class='muted'>{t['count']}</td></tr>"
        )
    threads_html = (
        "<h2>Последние треды</h2>"
        "<table><tr><th>время</th><th>subject</th><th>участники</th>"
        "<th>теги</th><th>#</th></tr>"
        + "".join(rows_t) + "</table>"
    )

    tasks = _load_tasks().get("tasks", [])
    open_tasks = [t for t in tasks if t.get("status") in ("open", "in_progress", "blocked")]
    rows_task = []
    for t in open_tasks[:10]:
        rows_task.append(
            f"<tr><td class='status-{_esc(t.get('status'))}'>{_esc(t.get('status'))}</td>"
            f"<td>{_esc(t.get('title'))}</td>"
            f"<td class='muted'>{_esc(t.get('owner') or '—')}</td></tr>"
        )
    tasks_html = ""
    if rows_task:
        tasks_html = (
            "<h2>Открытые tasks</h2>"
            "<table><tr><th>status</th><th>title</th><th>owner</th></tr>"
            + "".join(rows_task) + "</table>"
            "<p class='muted'>Полный список: <a href='/ui/tasks'>/ui/tasks</a></p>"
        )

    body = f"<h1>memory-mcp</h1>{presence_html}{threads_html}{tasks_html}"
    return _ui_page("memory-mcp", body)


async def ui_threads(request: Request) -> Response:
    include_archived = request.query_params.get("archived") == "1"
    threads = _collect_threads(include_archived=include_archived)
    rows = []
    for t in threads:
        tags = "".join(f"<span class='tag'>{_esc(x)}</span>" for x in t["tags"])
        rows.append(
            f"<tr><td class='muted'>{_esc(t['last_ts'][:16].replace('T',' '))}</td>"
            f"<td><a href='/ui/thread/{_esc(t['thread_id'])}'>{_esc(t['last_subject'])}</a></td>"
            f"<td class='muted'>{_esc(', '.join(t['participants']))}</td>"
            f"<td>{tags}</td>"
            f"<td class='muted'>{t['count']}</td></tr>"
        )
    toggle = ("<a href='/ui/threads'>без архивных</a>" if include_archived
              else "<a href='/ui/threads?archived=1'>показать архив</a>")
    body = (
        f"<h1>Треды</h1><p class='muted'>{toggle}</p>"
        "<table><tr><th>время</th><th>subject</th><th>участники</th><th>теги</th><th>#</th></tr>"
        + "".join(rows) + "</table>"
    )
    return _ui_page("Треды", body)


async def ui_thread(request: Request) -> Response:
    thread_id = request.path_params["thread_id"]
    thread_dir = MESSAGES_DIR / thread_id
    if not thread_dir.exists():
        return _ui_page("404", f"<p>Тред не найден: {_esc(thread_id)}</p>")
    msgs = sorted(thread_dir.glob("*.md"))
    parts = [f"<h1>{_esc(thread_id)}</h1>"]
    for mf in msgs:
        msg = _load_msg(mf)
        tags = "".join(f"<span class='tag'>{_esc(x)}</span>" for x in (msg.get("tags") or []))
        reactions = msg.get("reactions") or {}
        rx_html = ""
        if reactions:
            rx_html = "<span class='reactions'>" + " ".join(
                f"{_esc(v)}&nbsp;<small class='muted'>{_esc(k)}</small>"
                for k, v in reactions.items()
            ) + "</span>"
        cls = "msg arch" if msg.get("archived") else "msg"
        body = msg.get("body") or ""
        if msg.get("encrypted") == "age":
            body = "[тело зашифровано age — видно только получателю после расшифровки]"
        head = (
            f"<div class='msg-head'>"
            f"<b>{_esc(msg.get('from'))}</b> → {_esc(msg.get('to'))} "
            f"<span class='muted'>· {_esc(msg.get('timestamp'))} · "
            f"{_esc(msg.get('message_type') or 'prose')}</span> "
            f"{tags}{rx_html}"
            f"<div class='muted'>{_esc(msg.get('subject'))}</div>"
            f"</div>"
        )
        parts.append(f"<div class='{cls}'>{head}<div class='msg-body'>{_esc(body)}</div></div>")
    return _ui_page(thread_id, "".join(parts))


async def ui_notes(request: Request) -> Response:
    names = sorted(p.stem for p in SHARED_DIR.glob("*.md") if not p.stem.startswith("_"))
    rows = [f"<li><a href='/ui/note/{_esc(n)}'>{_esc(n)}</a></li>" for n in names]
    body = f"<h1>Shared notes</h1><ul>{''.join(rows) or '<li class=muted>пусто</li>'}</ul>"
    return _ui_page("Shared notes", body)


async def ui_note(request: Request) -> Response:
    name = request.path_params["name"]
    path = SHARED_DIR / f"{_slug(name)}.md"
    if not path.exists():
        return _ui_page("404", f"<p>Заметка не найдена: {_esc(name)}</p>")
    content = path.read_text()
    body = f"<h1>{_esc(name)}</h1><pre>{_esc(content)}</pre>"
    return _ui_page(name, body)


async def ui_tasks(request: Request) -> Response:
    tasks = _load_tasks().get("tasks", [])
    rows = []
    for t in sorted(tasks, key=lambda x: (x.get("status") == "done", x.get("status") == "dropped", x.get("updated", "")), reverse=False):
        tags = "".join(f"<span class='tag'>{_esc(x)}</span>" for x in (t.get("tags") or []))
        rows.append(
            f"<tr><td class='status-{_esc(t.get('status'))}'>{_esc(t.get('status'))}</td>"
            f"<td>{_esc(t.get('title'))}</td>"
            f"<td class='muted'>{_esc(t.get('owner') or '—')}</td>"
            f"<td>{tags}</td>"
            f"<td class='muted'>{_esc((t.get('updated') or '')[:16].replace('T',' '))}</td></tr>"
        )
    body = (
        "<h1>Shared tasks</h1>"
        "<table><tr><th>status</th><th>title</th><th>owner</th><th>tags</th><th>updated</th></tr>"
        + "".join(rows) + "</table>"
    )
    return _ui_page("Tasks", body)


async def ui_search(request: Request) -> Response:
    q = request.query_params.get("q", "").strip()
    form = (
        "<form class='search' method='get' action='/ui/search'>"
        f"<input type='search' name='q' placeholder='подстрока в subject/body' "
        f"value='{_esc(q)}'> <button>Искать</button>"
        "</form>"
    )
    body_parts = ["<h1>Поиск</h1>", form]
    if q:
        rows = []
        ql = q.lower()
        for msg in _iter_messages():
            hay = (msg.get("subject", "") + "\n" + (msg.get("body") or "")).lower()
            if ql not in hay:
                continue
            rows.append(
                f"<tr><td class='muted'>{_esc(msg['timestamp'][:16].replace('T',' '))}</td>"
                f"<td>{_esc(msg.get('from'))} → {_esc(msg.get('to'))}</td>"
                f"<td><a href='/ui/thread/{_esc(msg['thread_id'])}'>{_esc(msg['subject'])}</a></td>"
                f"</tr>"
            )
        rows.sort(reverse=True)
        body_parts.append(
            f"<p class='muted'>Найдено: {len(rows)}</p>"
            "<table><tr><th>время</th><th>от→кому</th><th>subject</th></tr>"
            + "".join(rows) + "</table>"
        )
    return _ui_page("Поиск", "".join(body_parts))


# --- run server ---

def main():
    async def health(_req):
        return PlainTextResponse("ok")

    app = mcp.streamable_http_app()
    app.add_middleware(AuthMiddleware)
    app.routes.append(Route("/health", health))

    if UI_USERS:
        app.routes.extend([
            Route("/ui", ui_index),
            Route("/ui/", ui_index),
            Route("/ui/threads", ui_threads),
            Route("/ui/thread/{thread_id:str}", ui_thread),
            Route("/ui/notes", ui_notes),
            Route("/ui/note/{name:str}", ui_note),
            Route("/ui/tasks", ui_tasks),
            Route("/ui/search", ui_search),
        ])

    import uvicorn
    uvicorn.run(app, host=BIND_HOST, port=BIND_PORT, log_level="info")


if __name__ == "__main__":
    main()
