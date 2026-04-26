# tw-nointeract-preflight-hook

An `on-launch` Taskwarrior hook that protects non-interactive clients (web UIs,
desktop GUIs, API wrappers) from accidentally running bulk-destructive commands
without user confirmation.

---

## The Problem

Taskwarrior's built-in confirmation prompts (`yes/no/all/quit`) require a live
terminal. When a GUI or web client runs `task` as a subprocess, there is no TTY
— the prompt gets no input, defaults to **no**, and the command silently modifies
zero tasks. Adding `rc.confirmation=no` removes the guard entirely. Neither
outcome is good.

```
$ task status:pending pro:myproject mod +urgent
This command will alter 23 tasks.
Modify task 12 'fix login bug'? (yes/no/all/quit) Task not modified.
Modified 0 tasks.
```

---

## The Solution

This hook intercepts mutating commands **before** Taskwarrior executes them.
When running under a non-interactive client (`TW_NOINTERACT=1`), it counts the
tasks that would be affected and — if the count exceeds a configurable threshold
— exits non-zero with a structured JSON signal on stderr. Taskwarrior aborts the
command. The client reads the signal, presents its own native confirmation UI,
and re-runs with `TW_PREFLIGHT_CONFIRMED=1` if the user approves.

```
User types:  "status:pending pro:myproject mod +urgent"
                         │
              hook counts matching tasks → 23
                         │
              exits 1 + JSON signal on stderr
                         │
              client shows: "This will modify 23 tasks. Proceed?"
                         │
          [Yes, do it]          [Cancel]
               │
     re-run with TW_PREFLIGHT_CONFIRMED=1
               │
          hook steps aside → command runs
```

---

## Protocol

The hook communicates entirely through environment variables and stderr.
No files, no sockets, no client-specific dependencies.

### Input (environment variables set by the client)

| Variable | Required | Description |
|---|---|---|
| `TW_NOINTERACT=1` | yes | Activates the hook. Any non-terminal client should set this. |
| `TW_PREFLIGHT_VERB=modify` | yes | The command verb being run (`modify`, `delete`, `done`, …). |
| `TW_PREFLIGHT_FILTER=…` | yes | Filter tokens as a space-separated, shlex-safe string. |
| `TW_PREFLIGHT_CMD=…` | no | Full original command string (for display purposes only). |
| `TW_PREFLIGHT_THRESHOLD=3` | no | Task count above which to block. Default: 3. |
| `TW_PREFLIGHT_CONFIRMED=1` | no | Set on re-run after user confirms. Hook exits 0 immediately. |

`TW_CLIENT=<name>` is also recommended (e.g. `TW_CLIENT=web`) to identify the
caller, though the hook does not require it.

### Output (on block)

One JSON line on **stderr**, then exit 1:

```json
{
  "type":      "tw_preflight",
  "count":     23,
  "verb":      "mod",
  "filter":    "status:pending pro:myproject",
  "cmd":       "status:pending pro:myproject mod +urgent",
  "threshold": 3
}
```

Taskwarrior treats exit 1 as a hook failure and aborts the command.
The client detects the signal by scanning stderr for a line starting with `{`
that parses as JSON with `"type": "tw_preflight"`.

### On pass

Exits 0 immediately when any of the following are true:
- `TW_NOINTERACT` is not set (CLI / interactive session — hook is invisible)
- `TW_PREFLIGHT_CONFIRMED=1` (user already confirmed)
- No verb or filter provided in env vars
- Task count ≤ threshold

---

## Installation

```bash
cp on-launch_nointeract-preflight.py ~/.task/hooks/
chmod +x ~/.task/hooks/on-launch_nointeract-preflight.py
```

Or via [awesome-taskwarrior](https://github.com/linuxcaffe/awesome-taskwarrior):

```bash
awesome install nointeract-preflight
```

---

## Client Integration Guide

To use this hook, your client needs to do three things.

### 1. Set the environment

Always set `TW_NOINTERACT=1` (and `TW_CLIENT=<name>`) on every subprocess call
to `task`. This is the master switch — without it the hook is completely inert
and adds zero overhead for CLI users.

### 2. Before a mutating command, set the preflight vars

Parse the user's command to extract the filter and verb, then add them to the
subprocess environment:

```python
env['TW_PREFLIGHT_VERB']   = verb          # e.g. "modify"
env['TW_PREFLIGHT_FILTER'] = filter_str    # e.g. "status:pending pro:myproject"
env['TW_PREFLIGHT_CMD']    = original_cmd  # full string, for display
```

### 3. Detect the signal and present confirmation

If the subprocess exits non-zero, scan stderr for the JSON signal:

```python
for line in result.stderr.splitlines():
    if line.strip().startswith('{'):
        try:
            signal = json.loads(line)
            if signal.get('type') == 'tw_preflight':
                # present confirmation UI
                # on confirm: re-run with env['TW_PREFLIGHT_CONFIRMED'] = '1'
        except json.JSONDecodeError:
            pass
```

### 4. On confirmation, re-run

```python
env['TW_PREFLIGHT_CONFIRMED'] = '1'
# remove TW_PREFLIGHT_* vars (optional but clean)
result = subprocess.run(['task', ...], env=env, ...)
```

---

## Reference Implementation: tw-web

[tw-web](https://github.com/linuxcaffe/tw-web) is the reference client.

- `TW_NOINTERACT=1` and `TW_CLIENT=web` are set on every subprocess call
- `/api/run` parses the command, sets the preflight env vars, then runs `task`
- The preflight JSON is detected in the response and returned to the browser as
  `{"preflight": true, "count": N, "verb": "…", "filter": "…"}`
- The command-mode output bar renders **"This will modify N tasks matching
  \<filter\>. Proceed?"** with green **Yes** / **Cancel** buttons
- Yes re-POSTs with `confirmed: true`; the backend sets `TW_PREFLIGHT_CONFIRMED=1`

---

## Supported Verbs

The hook activates on verbs it considers mutating:

`modify` / `mod` / `mo` · `delete` / `del` · `done` / `do` / `don` ·
`start` / `sta` · `stop` / `sto` · `annotate` / `ann` · `append` / `app` ·
`prepend` / `pre` · `duplicate` / `dup` · `purge`

Single-target verbs (`add`, `sync`, `undo`, `import`) are excluded — they cannot
produce bulk-dangerous operations.

---

## Performance

For CLI users (`TW_NOINTERACT` unset): the hook exits at line 1. Zero overhead.

For non-interactive clients on non-bulk commands (count ≤ threshold): one fast
`task count` call with `rc.hooks=off` (no hook recursion), typically < 50 ms.

For blocked commands: the count call is the only work done. The main command
never runs until the client re-submits with `TW_PREFLIGHT_CONFIRMED=1`.

---

## License

MIT — see [LICENSE](LICENSE)

Author: linuxcaffe + Claude Sonnet 4.6
