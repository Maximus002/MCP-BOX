#!/usr/bin/env python3
"""memory-mcp webhook listener for Windows.

Accepts POST /webhook with JSON body, validates X-MemoryMCP-Secret header,
shows Windows toast notification via BurntToast PowerShell module.
"""
import hmac
import json
import logging
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8787
SECRET_FILE = Path(__file__).parent / "secret"
LOG_FILE = Path(__file__).parent / "listener.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("listener")


def load_secret():
    try:
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        log.error("secret file not found: %s", SECRET_FILE)
        return None


SECRET = load_secret()


def _escape_ps_single_quoted(s: str) -> str:
    return s.replace("'", "''")


def show_toast(subject: str, sender: str):
    safe_sender = _escape_ps_single_quoted(sender)
    safe_subject = _escape_ps_single_quoted(subject)
    ps_cmd = (
        "Import-Module BurntToast -ErrorAction Stop; "
        "New-BurntToastNotification "
        f"-Text 'memory-mcp: {safe_sender}','{safe_subject}' "
        "-AppLogo $null"
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            check=True,
            timeout=10,
            capture_output=True,
        )
        if r.stderr:
            log.warning("toast stderr: %s", r.stderr.decode("utf-8", errors="replace"))
    except Exception as e:
        log.error("toast failed: %s", e)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info("%s - %s", self.client_address[0], fmt % args)

    def do_POST(self):
        if self.path not in ("/", "/notify", "/webhook"):
            self.send_response(404)
            self.end_headers()
            return

        got = self.headers.get("X-MemoryMCP-Secret", "")
        if not SECRET or not hmac.compare_digest(got, SECRET):
            log.warning("bad/missing secret from %s", self.client_address[0])
            self.send_response(401)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            log.error("bad json: %s", e)
            self.send_response(400)
            self.end_headers()
            return

        event = payload.get("event", "?")
        if event == "message":
            sender = payload.get("from", "?")
            subject = payload.get("subject", "(no subject)")
            msg_id = payload.get("message_id", "?")
            log.info("webhook: from=%s subject=%r id=%s", sender, subject, msg_id)
            show_toast(subject, sender)
        else:
            log.info("unknown event: %s", event)

        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_response(404)
        self.end_headers()


def main():
    if SECRET is None:
        log.error("no secret loaded, exiting")
        sys.exit(1)
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    log.info("listener starting on %s:%d", LISTEN_HOST, LISTEN_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
