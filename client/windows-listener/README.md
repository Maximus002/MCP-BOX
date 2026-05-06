# memory-mcp webhook listener (Windows)

HTTP webhook listener for Windows: receives notifications from the memory-mcp
server and shows native toast notifications via PowerShell's
[BurntToast](https://github.com/Windos/BurntToast) module. Symmetric to
`client/mac-listener/`.

## Requirements

- Python 3.10+ (uses `pythonw.exe` — no console window).
- PowerShell 5.1+ (built into Windows 10/11).
- BurntToast (auto-installed by `install.ps1`).

## Files

- `listener.py` — the HTTP server (Python stdlib, no deps).
- `install.ps1` — installs BurntToast, opens firewall, registers Scheduled
  Task to run the listener at logon. Must be run as Administrator.
- `uninstall.ps1` — reverses the above. BurntToast stays installed unless
  removed manually.

## Install

1. Copy this folder somewhere stable, e.g. `C:\Users\<YOU>\.claude\windows-listener\`.
2. Create a file named `secret` in that folder; its content must match
   `webhook_secret` in the server's `config.yaml`. **Do not commit this file.**
3. Edit `install.ps1` and set the variables in the `--- CONFIGURE THESE ---`
   block (`$here`, `$python`, `$user`, optionally `$lanCidr` for tighter
   firewall).
4. Run PowerShell as Administrator and execute:
   ```powershell
   .\install.ps1
   ```
5. On the server host, edit `/etc/memory-mcp/config.yaml`:
   ```yaml
   webhooks:
     <your-identity>: "http://<THIS_PC_IP>:8787/notify"
   ```
   …and `systemctl restart memory-mcp`.

## Verify

```powershell
# Health check
Invoke-WebRequest http://127.0.0.1:8787/health -UseBasicParsing
# → 200 ok
```

```bash
# Test webhook (from any LAN host with Python or curl)
SECRET=$(cat secret)
curl -X POST http://<windows-ip>:8787/webhook \
  -H "X-MemoryMCP-Secret: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"event":"message","from":"agent_a","subject":"test","message_id":"msg_test","thread_id":"t"}'
# → HTTP 204 + a Windows toast appears
```

## Uninstall

```powershell
.\uninstall.ps1
```

Stops and removes the Scheduled Task, kills running listener processes,
removes the firewall rule. The `secret` file and logs are left in place —
delete the folder manually if you want a clean wipe.

## Modes

This listener runs in **notify** mode only — it shows a toast on incoming
webhooks; the agent reads `inbox()` itself when the user opens a fresh
session.

A `claude -p "..."` mode (auto-spawn a headless agent run on each webhook,
analogous to the macOS listener's `LISTENER_ACTION=claude`) is **not**
provided here because most subscription accounts (Claude MAX, Pro) don't
support headless authentication. If you have an `ANTHROPIC_API_KEY`
available and want auto-respond, the macOS listener's pattern can be
ported — pull request welcome.

## Logs

`listener.log` in this folder, plus stdout (visible if you run the script
manually rather than via Scheduled Task). Rotate or truncate manually as
needed.

## Known limitations

- Listener runs as the logged-in user (`-LogonType Interactive`), so it
  only works while that user is logged in. For continuous service across
  reboots without login, use `-LogonType S4U` or a service account, but
  toast notifications require an interactive session anyway.
- Firewall rule defaults to `192.168.0.0/16` inbound. Tighten via the
  `$lanCidr` variable in `install.ps1` if your LAN is more specific.
- Shared-secret auth over plain HTTP — LAN-only by design. Front with
  TLS (caddy/nginx reverse-proxy) if your threat model includes a
  passive sniffer on the LAN.
