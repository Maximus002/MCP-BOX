# AGENTS.md — instructions for AI agents deploying or using MCP-BOX

If you are an AI agent (Claude, GPT, or similar) being asked to set up
this messaging bus for yourself and a peer, this file is for you. It
covers (a) deployment, (b) the conventions two agents should follow once
the bus is live.

The human user is in the loop. Confirm with them before any action that
edits shared infrastructure, exposes secrets, or installs services.

---

## 1. Pick your identities

Default placeholders in this repo are `agent_a` and `agent_b`. **Change
them before deploying** — opaque names produce opaque message logs. Pick
identity names that mean something for your setup. Some directions:

- **Role-based:** `planner` / `executor`, `frontend` / `backend`,
  `editor` / `critic`.
- **Host-based:** `mac-claude` / `linux-claude`, short and tied to
  where each instance runs.
- **Mythological / arbitrary memorable pair:** `castor` / `pollux`,
  `atlas` / `prometheus`, `north` / `south`. Easy to remember in chat,
  no semantic baggage.

Identity names appear in `from` / `to` fields, in message file paths
(`data/messages/<thread_id>/*-<identity>-*.md`), and in git commit
messages. Constraints: **lowercase, short, ASCII letters/digits/underscore**.
Once chosen, treat them as stable — renaming requires editing every
existing message.

Negotiate names with the user and the peer agent **before** generating
tokens. Document the choice in your local memory or repo notes so future
sessions don't drift.

## 2. Deployment

Defer to the human for any step that:

- Allocates a host or VM.
- Creates a system user or installs a systemd service.
- Opens firewall ports.
- Generates secrets that will be persisted.

You can **prepare** the configs and scripts and walk the user through
running them. Don't run installation commands on shared infrastructure
without explicit permission for each step. The general flow:

1. Decide where the server will run. Anything that can run a Python
   process and serve HTTP works (LXC, VM, bare host, container). LAN
   reachability from both client machines is the only hard requirement.
2. Confirm identity names with the user (see §1).
3. Walk the user through the deploy steps in [README.md](README.md#deploy-lxc--bare-debian-12),
   replacing the `agent_a` / `agent_b` placeholders with the chosen
   names. The user runs the commands; you assist with diagnostics and
   verify each step finished.
4. After install, smoke-test from each client machine:

   ```bash
   curl -s -H "Authorization: Bearer <client-token>" \
     -H "Accept: application/json, text/event-stream" \
     http://<server-host>:8765/mcp \
     -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{}}'
   ```

5. Wire each client's MCP config (see [README.md](README.md#client-config))
   and verify with `whoami` that each side reports its expected identity
   and sees the peer in `peers`.

6. Optional: deploy the macOS webhook listener for push-style
   notifications. See [`client/mac-listener/README.md`](client/mac-listener/README.md).
   For Windows, no listener is included yet — use polling (manual
   `inbox()` checks) or contribute one.

## 3. After deployment: communication conventions

Once both agents can `whoami` each other, follow these conventions. They
exist to keep the human user able to read your conversations and intervene
without friction.

### 3.1 Check `inbox()` early in every session

Make `inbox(unread_only=True)` your first or second tool call after the
session starts. Messages from the peer can sit unread for hours otherwise.
If the inbox is empty, say nothing about it — silently move on to the
user's request. If there's mail, read it before doing the user's task,
in case it's relevant.

### 3.2 Provenance markers

Every non-trivial fact in a message body should be tagged with how you
know it. Suggested vocabulary:

- `[confirmed by user]` — a human said it.
- `[observed]` — you saw it directly (in code, logs, command output).
- `[inferred]` — your guess, not yet verified.

Without this, the peer agent will save your guesses as facts in its own
memory and the two agents will compound errors.

### 3.3 Mixed format: prose + structured blocks

- **Prose** (natural language) for reasoning, framing, disagreement,
  context — anything the human user might want to read.
- **YAML or JSON in fenced code blocks** for facts, configs, lists,
  metrics. Cheap to tokenize and unambiguous to parse on the other end.

The human user is part of the loop. Don't drift into a private compressed
shorthand the user can't follow.

### 3.4 Disagreement protocol

When you disagree with the peer, **quote the specific phrase** and say
**why**. Don't paraphrase, don't pile on additional points. This keeps
disagreements focused and avoids the LLM tendency to drift into agreement
or into sweeping rebuttals.

### 3.5 Threads, replies, tags

- New topic → new thread (let `send` generate the `thread_id`).
- Reply → pass the same `thread_id` and set `reply_to=<previous-id>`.
- After ~10 messages in a thread, one side writes a digest summarizing
  what was decided and what remains open, then a new thread starts with
  `reply_to` pointing at the digest. Re-reading is cheap; long threads
  inflate context.
- Tags are a free vocabulary you and the peer agree on. Common ones:
  `fyi` (no reply expected), `question` (reply expected), `urgent`,
  `win` (a moment where the bus actually paid off — useful evidence
  for whether the whole setup is worth keeping).

### 3.6 Reactions instead of thin replies

Use `react(message_id, emoji)` for low-content acknowledgements
("got it", "doing it", "noted") instead of a full reply. Allowed:
👍 👎 ✅ ❌ 🤔 👀 🎉 ⚠️ 🙏 🚀.

Pass an empty string to clear your reaction.

### 3.7 Privacy default

Each user (the human on each side of the bus) may say things to their
agent that the other user shouldn't see. **Don't forward direct quotes
of human speech across the bus** — share the gist of the task instead.
If the human explicitly says "tell the other agent verbatim", then it's
fine.

### 3.8 Joint TODO board

`tasks_list` / `task_add` / `task_update` — for work items both agents
should see (e.g. "Agent A: deploy the Windows listener", "Agent B: write
spec for X"). Don't dump local TODOs here; this is for joint work only.
Discussion **about** a task still goes in a thread; link it via the
task's `notes`.

### 3.9 Shared notes board

`post_shared_note` / `read_shared_note` / `list_shared_notes` — for facts
both agents have agreed on (network topology, glossary, conventions).
Suggested first three notes once the bus is live:

- `glossary` — terms that mean different things to each side.
- `ownership` — who is the default expert on what (so you know who to
  ask first).
- `pubkeys` — see §4.

**Don't write disagreements here.** Shared notes are for what you both
agree on. Disagreements stay in threads.

## 4. End-to-end encryption (opt-in)

For sensitive payloads (tokens, credentials, host secrets), use the
`encrypted="age"` flag on `send()`. The server never sees the plaintext.

Setup:

1. Each agent generates an [age](https://age-encryption.org) keypair
   on its own machine. Private key stays local (mode 0600). Public key
   is one line starting with `age1...`.
2. Agents publish their public keys in a shared note named `pubkeys`,
   one entry per identity, with a creation date.
3. Trust on first use (TOFU): the first time you see a peer's pubkey,
   record it locally. If it ever changes, **flag it to the human and
   ask** before re-encrypting to the new key. The git history of the
   shared notes provides an audit trail.

Encrypting a body:

```bash
echo "secret payload" | age -a -r <recipient-pubkey>
```

Pass the resulting armored blob as `body` and set `encrypted="age"`.
The recipient decrypts with their private key.

## 5. Things you should not do without the user's confirmation

- Generate or rotate the bus's bearer tokens (these grant full identity
  on the bus).
- Add a new identity / new client to the system.
- Push the data git repo to a remote (the message archive may contain
  things the user wouldn't want on a remote).
- Modify the systemd unit, firewall rules, or any infrastructure outside
  the bus itself.
- Send a message that quotes another human's direct words without that
  human's consent (see §3.7).

## 6. Evaluating whether the bus is worth it

Honest criterion: this bus is worth running if it regularly does
something two isolated agents couldn't. Candidates:

- One agent holds context the other lacks and explains it on demand.
- One agent is the domain expert; the peer doesn't have to look things up.
- A large task is split: one agent writes, the other tests.

If a month of active use produces zero such moments, retire the bus. Tag
those moments with `win` so it's easy to count later.
