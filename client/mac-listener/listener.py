#!/usr/bin/env python3
"""
memory-mcp webhook listener (macOS side).

Listens for POST /notify from the memory-mcp server (on homelab),
then spawns a headless Claude session (`claude -p "..."`) which picks up
the new message from inbox and answers.

Behavior:
- Debounce bursts: multiple POSTs within ~1s collapse into a single Claude run.
- While a Claude run is in progress, further POSTs set a "dirty" flag;
  when the current run exits, one more run fires to cover the late message.
- Hard budget cap per run via --max-budget-usd (safety against runaway).
- Never blocks the HTTP response: handler replies 200 immediately, work
  happens in a worker thread.

Actions on incoming webhook (LISTENER_ACTION env):
  "notify" (default) — show native macOS notification. Works with
     MAX-подписка (OAuth auth), zero API cost.
  "claude"           — spawn `claude -p "..."` to auto-answer. Requires
     ANTHROPIC_API_KEY in env (launchd daemon cannot access Claude.app's
     OAuth keychain). Separate billing from MAX subscription.

Config via env:
  LISTENER_PORT         (default 8787)
  LISTENER_BIND         (default 0.0.0.0)
  LISTENER_DRY_RUN      (if "1" — log but take no action)
  LISTENER_ACTION       (default "notify"; alt: "claude")
  LISTENER_WORKDIR      (default ~; used when action=claude)
  LISTENER_MAX_BUDGET   (default 0.50; USD per Claude run, when action=claude)
  LISTENER_SECRET_FILE  (path to file with shared secret; empty = auth off)
  LISTENER_ACTIVATE_APP (if "1" — also bring Claude.app to foreground on notify)
"""
from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("LISTENER_PORT", "8787"))
BIND = os.environ.get("LISTENER_BIND", "0.0.0.0")
DRY_RUN = os.environ.get("LISTENER_DRY_RUN") == "1"
ACTION = os.environ.get("LISTENER_ACTION", "notify").lower()
WORKDIR = os.environ.get("LISTENER_WORKDIR", os.path.expanduser("~"))
MAX_BUDGET = os.environ.get("LISTENER_MAX_BUDGET", "0.50")
SECRET_FILE = os.environ.get("LISTENER_SECRET_FILE", "")
ACTIVATE_APP = os.environ.get("LISTENER_ACTIVATE_APP") == "1"

# shared-secret auth. expected value is read once at startup from SECRET_FILE.
# empty file / missing path = auth disabled (warning logged on startup).
SECRET_HEADER_NAME = "X-MemoryMCP-Secret"
try:
    EXPECTED_SECRET = open(SECRET_FILE).read().strip() if SECRET_FILE else ""
except OSError:
    EXPECTED_SECRET = ""

CLAUDE_GLOB = os.path.expanduser(
    "~/Library/Application Support/Claude/claude-code/*/"
    "claude.app/Contents/MacOS/claude"
)

DEBOUNCE_SEC = 1.0          # collapse bursts
RUN_TIMEOUT_SEC = 600       # hard ceiling on a single claude run

log = logging.getLogger("memory-mcp-listener")

# --- claude invocation ---


def find_claude() -> str | None:
    candidates = sorted(glob.glob(CLAUDE_GLOB))
    return candidates[-1] if candidates else None


def build_prompt(payload: dict) -> str:
    return (
        "Тебя разбудил webhook memory-mcp — в inbox появилось новое сообщение. "
        f"Метаданные из webhook:\n"
        f"  from: {payload.get('from')!r}\n"
        f"  subject: {payload.get('subject')!r}\n"
        f"  thread_id: {payload.get('thread_id')!r}\n"
        f"  message_id: {payload.get('message_id')!r}\n\n"
        "Что делать:\n"
        "1. Вызови mcp__memory-mcp__inbox(unread_only=True) для проверки.\n"
        "2. Прочитай сообщение через mcp__memory-mcp__read(message_id) "
        "(это пометит его прочитанным).\n"
        "3. Если нужен полный контекст треда — mcp__memory-mcp__thread(thread_id).\n"
        "4. Ответь по существу через mcp__memory-mcp__send(...) с тем же "
        "thread_id и reply_to=<id полученного>.\n"
        "5. Соблюдай конвенции из AGENTS.md (провенанс, смешанный формат, ack).\n"
        "6. Завершай сессию после ответа — не висишь в ожидании."
    )


def run_claude(payload: dict) -> None:
    claude = find_claude()
    if not claude:
        log.error("claude binary not found via %s", CLAUDE_GLOB)
        return

    prompt = build_prompt(payload)

    if DRY_RUN:
        log.info("DRY_RUN — would run: %s -p <prompt %d chars>", claude, len(prompt))
        return

    try:
        proc = subprocess.run(
            [claude, "-p", prompt, "--max-budget-usd", MAX_BUDGET],
            cwd=WORKDIR,
            timeout=RUN_TIMEOUT_SEC,
            capture_output=True,
            text=True,
        )
        log.info(
            "claude finished rc=%d stdout_len=%d stderr_len=%d",
            proc.returncode, len(proc.stdout or ""), len(proc.stderr or ""),
        )
        if proc.returncode != 0:
            if proc.stdout:
                log.warning("claude stdout: %s", proc.stdout[:500])
            if proc.stderr:
                log.warning("claude stderr: %s", proc.stderr[:500])
    except subprocess.TimeoutExpired:
        log.error("claude run timed out after %ds", RUN_TIMEOUT_SEC)
    except Exception as e:
        log.exception("claude run failed: %s", e)


# --- notification action ---


def _osa_quote(s: str) -> str:
    """Escape a string for safe inclusion in an AppleScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify_user(payload: dict) -> None:
    """Show a native macOS notification. Optionally bring Claude.app forward."""
    sender = str(payload.get("from") or "?")
    subject = str(payload.get("subject") or "(без темы)")

    title = f"memory-mcp: {sender}"
    body = subject

    script = (
        f'display notification "{_osa_quote(body)}" '
        f'with title "{_osa_quote(title)}" '
        f'sound name "Ping"'
    )

    if DRY_RUN:
        log.info("DRY_RUN — would notify: %s / %s", title, body)
        return

    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            timeout=5, capture_output=True, text=True, check=False,
        )
        log.info("notified: %s / %s", title, body)
    except Exception as e:
        log.exception("osascript notify failed: %s", e)

    if ACTIVATE_APP:
        try:
            subprocess.run(
                ["/usr/bin/osascript", "-e",
                 'tell application "Claude" to activate'],
                timeout=5, capture_output=True, text=True, check=False,
            )
        except Exception as e:
            log.warning("activate Claude.app failed: %s", e)


# --- action dispatch ---


def dispatch(payload: dict) -> None:
    if ACTION == "notify":
        notify_user(payload)
    elif ACTION == "claude":
        run_claude(payload)
    else:
        log.error("unknown LISTENER_ACTION=%r (expected notify|claude)", ACTION)


# --- debouncing worker ---

_lock = threading.Lock()
_pending_payload: list[dict] = []   # queue of payloads waiting to be processed
_wake = threading.Event()


def worker() -> None:
    while True:
        _wake.wait()
        # small window to coalesce bursts
        _wake.clear()
        # drain pending; keep only the latest (enough for a "there's mail" signal)
        with _lock:
            if not _pending_payload:
                continue
            payload = _pending_payload[-1]
            _pending_payload.clear()
        try:
            dispatch(payload)
        except Exception:
            log.exception("worker iteration crashed")


# --- http handler ---


def _constant_time_equal(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


class Handler(BaseHTTPRequestHandler):
    def _reject(self, code: int, reason: str) -> None:
        body = reason.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        # shared-secret auth
        if EXPECTED_SECRET:
            got = self.headers.get(SECRET_HEADER_NAME, "")
            if not _constant_time_equal(got, EXPECTED_SECRET):
                log.warning(
                    "reject POST %s from %s — bad/missing %s header",
                    self.path, self.client_address[0], SECRET_HEADER_NAME,
                )
                self._reject(401, "unauthorized\n")
                return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"_raw": raw}

        log.info("webhook %s: %s", self.path, payload)

        with _lock:
            _pending_payload.append(payload)
        _wake.set()

        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        # simple health endpoint
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"memory-mcp listener ok\n")

    def log_message(self, *a, **kw) -> None:  # silence default stderr spam
        pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    log.info(
        "starting listener bind=%s port=%d dry_run=%s action=%s auth=%s activate_app=%s",
        BIND, PORT, DRY_RUN, ACTION,
        "on" if EXPECTED_SECRET else "OFF (open)",
        ACTIVATE_APP,
    )
    if not EXPECTED_SECRET:
        log.warning(
            "no shared secret — /notify accepts any POST on LAN. "
            "set LISTENER_SECRET_FILE to enable auth."
        )

    t = threading.Thread(target=worker, name="claude-worker", daemon=True)
    t.start()

    HTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
