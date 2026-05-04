# memory-mcp webhook listener (macOS)

Tiny HTTP listener that receives webhook POSTs from the memory-mcp server
and triggers an action on incoming mail.

Two actions supported (`LISTENER_ACTION` env):

- **`notify`** (default) — show a native macOS notification (`osascript`).
  Works with Claude MAX subscription, zero API cost. The user then opens
  Claude.app manually to handle the message.
- **`claude`** — spawn `claude -p "..."` headlessly to auto-respond.
  Requires `ANTHROPIC_API_KEY` in env because the launchd daemon cannot
  access Claude.app's OAuth keychain. Separate billing from MAX
  subscription.

## Files

- `listener.py` — the server itself (Python stdlib, no deps).
- `com.example.memory-mcp-listener.plist` — example LaunchAgent. Rename
  the `Label` and update paths to match your username before installing.

## Deploy

macOS TCC blocks LaunchAgents from opening files in `~/Documents/`, so the
script must live outside it. Copy it to `~/.claude/mac-listener/`:

```bash
mkdir -p ~/.claude/mac-listener
cp listener.py ~/.claude/mac-listener/listener.py

# shared-secret auth (must match /etc/memory-mcp/config.yaml webhook_secret)
printf '%s' "<same-value-as-server-webhook_secret>" > ~/.claude/mac-listener/secret
chmod 600 ~/.claude/mac-listener/secret

# adjust the plist for your username, then install
sed "s|<YOUR_USER>|$USER|g" com.example.memory-mcp-listener.plist \
  > ~/Library/LaunchAgents/com.example.memory-mcp-listener.plist
launchctl load ~/Library/LaunchAgents/com.example.memory-mcp-listener.plist
```

The secret file is NOT in git (`.gitignore`). Generate one identical value
on both sides: `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.

Logs at `~/Library/Logs/memory-mcp-listener{,.err}.log`.

Health: `curl http://127.0.0.1:8787/health` → `memory-mcp listener ok`.

## Wire to server

On the server host, edit `/etc/memory-mcp/config.yaml`:

```yaml
webhooks:
  agent_a: "http://<your-mac-lan-ip>:8787/notify"
```

…and `systemctl restart memory-mcp`. Pin the Mac's LAN IP with a DHCP
reservation or use mDNS.

## Env knobs (in the plist)

- `LISTENER_ACTION` — `notify` (default) or `claude`.
- `LISTENER_DRY_RUN=1` — log but take no action (for testing).
- `LISTENER_PORT`, `LISTENER_BIND` — change listen address.
- `LISTENER_ACTIVATE_APP=1` — on `notify`, also bring Claude.app to foreground.
- `LISTENER_MAX_BUDGET` — (action=claude only) caps each claude run, e.g. `0.50`.
- `LISTENER_WORKDIR` — (action=claude only) directory where `claude -p` runs.
- `LISTENER_SECRET_FILE` — path to shared-secret file (auth).

## First-run notification permission

macOS shows notifications via `osascript`, which inherits permission from
the bundle identifier `com.apple.ScriptRunner`. The first notification often
arrives silently because the user hasn't granted permission yet. Grant it
via **System Settings → Notifications → Script Editor** (or `osascript`),
set "Allow Notifications" + "Banners" / "Alerts".

## Behavior notes

- Debounces bursts within ~1s into a single dispatched action.
- HTTP handler always replies 200 immediately — work happens in a worker
  thread so the upstream server never blocks.
- `RUN_TIMEOUT_SEC=600` hard ceiling on a single Claude run (action=claude).

## Known limitations

- Claude CLI path is discovered via glob — works across version bumps of
  Claude Desktop but relies on the Desktop app being installed.
- Shared-secret auth is symmetric and transported over plain HTTP on the
  LAN. If your threat model includes a passive sniffer on the LAN, front
  with TLS (caddy/nginx reverse-proxy).
