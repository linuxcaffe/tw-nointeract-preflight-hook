#!/usr/bin/env python3
"""
on-launch_nointeract-preflight  —  bulk-operation guard for non-interactive clients.

When TW_NOINTERACT=1, detects mutating commands that would affect more tasks
than the configured threshold and exits non-zero with a structured JSON signal
on stderr so the client can present a confirmation UI before proceeding.

Environment variables (set by the calling client):
  TW_NOINTERACT=1            — activate this hook (any non-terminal client)
  TW_PREFLIGHT_CONFIRMED=1   — skip check; client already obtained confirmation
  TW_PREFLIGHT_VERB=modify   — the command verb (modify/delete/done/start/…)
  TW_PREFLIGHT_FILTER=…      — filter tokens (space-separated, shlex-safe)
  TW_PREFLIGHT_CMD=…         — full original command string (for display only)
  TW_PREFLIGHT_THRESHOLD=3   — task count above which to block (default: 3)

On block, writes to stderr (one JSON line):
  {"type":"tw_preflight","count":N,"verb":"…","filter":"…","cmd":"…"}
and exits 1.  Taskwarrior aborts the command; the client parses the signal.

On pass (count ≤ threshold, confirmed, or non-interactive not active): exits 0.
"""

import os
import sys
import json
import shlex
import subprocess

def main():
    # Only act for non-interactive clients
    if not os.environ.get('TW_NOINTERACT'):
        sys.exit(0)

    # Client already confirmed — step aside
    if os.environ.get('TW_PREFLIGHT_CONFIRMED'):
        sys.exit(0)

    verb       = os.environ.get('TW_PREFLIGHT_VERB', '').strip()
    filter_str = os.environ.get('TW_PREFLIGHT_FILTER', '').strip()
    cmd_str    = os.environ.get('TW_PREFLIGHT_CMD', '').strip()

    # Nothing to evaluate
    if not verb or not filter_str:
        sys.exit(0)

    try:
        threshold = int(os.environ.get('TW_PREFLIGHT_THRESHOLD', '3'))
    except ValueError:
        threshold = 3

    # Count tasks matching the filter — hooks off so we don't recurse
    try:
        filter_args = shlex.split(filter_str)
        result = subprocess.run(
            ['task', 'rc.hooks=off', 'rc.verbose=nothing'] + filter_args + ['count'],
            capture_output=True, text=True, timeout=5
        )
        count = int(result.stdout.strip()) if result.returncode == 0 else 0
    except Exception:
        sys.exit(0)  # on any error, don't block — fail open

    if count > threshold:
        signal = {
            'type':      'tw_preflight',
            'count':     count,
            'verb':      verb,
            'filter':    filter_str,
            'cmd':       cmd_str,
            'threshold': threshold,
        }
        print(json.dumps(signal), file=sys.stderr)
        sys.exit(1)

    sys.exit(0)

main()
