---
name: htb-cli
description: Explore, select, and solve Hack The Box items (challenges, machines, sherlocks) from the terminal using the htbconsole CLI. Use when the user wants to browse HTB content, find unsolved items, pull challenge files, start containers, or submit flags without opening the TUI.
---

# HTB via the htbconsole CLI

One-shot HTB API access. Prints **minimal fields as YAML** by default; add `--raw`
for the full JSON, `--pick <dotted.path>` to drill (e.g. `--pick 0.id`, `--pick info.name`).

## Setup

Needs an HTB API token in `HTB_TOKEN`. In this repo:

```bash
set -a; source ./token.txt; set +a      # exports HTB_TOKEN (+ CTF_TOKEN)
```

Invoke as `python3 -m htbconsole cli htb <cmd>` (or `htbconsole cli htb <cmd>` if installed).
Run `python3 -m htbconsole cli` with no args to see the full generated command list.

The examples below write **`htb`** as shorthand for `python3 -m htbconsole cli htb`
(optionally `alias htb='python3 -m htbconsole cli htb'`).

## Workflow: explore → select → solve

### 1. Explore (find unsolved work)

```bash
# Challenges — status=incompleted = UNSOLVED (default list mixes solved in)
htb chal list status=incompleted per_page=20
htb chal list status=incompleted per_page=50 page=2   # paginate
htb chal categories                                   # category id/name map

# Machines — no server-side unsolved filter; check the owns flags per item
htb machine list per_page=20        # unsolved = authUserInUserOwns / authUserInRootOwns false (--raw to see them)
htb machine retired per_page=20
htb machine active                  # what's running now

# Sherlocks (DFIR) — unsolved = is_owned false / progress < 100
htb sherlock list status=incompleted per_page=20

# Season
htb season list
```

Filtering: `key=value` pairs pass straight through as query params. Verified useful:
`status=incompleted` (unsolved), `per_page=`, `page=`. Other server-side filters exist
but need exact param formats — when unsure, list broadly and filter client-side with
`--raw --pick data` piped through a JSON/`jq` filter (e.g. select `is_owned == false`).

### 2. Select (inspect one item)

```bash
htb chal info <id>            # points, category, description, download flag, solved state
htb chal writeup <id>         # official/community writeup links
htb machine profile <name>   # os, difficulty, ip, owns
htb sherlock info <id>        # description
htb sherlock tasks <id>      # the questions to answer (masked_flag shows format)
```

### 3. Solve

```bash
# Challenge files
htb chal link <id>                 # signed download URL (url + expiry), no download
htb chal download <id> <path>      # fetch + save the zip (path is REQUIRED)

# Challenge container (for pwn/web/etc. that need a live target)
htb chal start <id>                # spawn container -> returns ip:port in the message
htb chal stop  <id>

# Machines: the CLI has no "start" verb — use the generic POST escape hatch:
htb post /api/v4/vm/spawn     machine_id=<id>     # start a machine
htb post /api/v4/vm/terminate machine_id=<id>     # stop

# Submit flags / answers
htb chal submit <id> HTB{...}
htb machine submit <id> HTB{...}                  # user or root flag
htb sherlock submit <sherlock-id> <task-id> <answer>
```

Any endpoint not wrapped by a named command is reachable via
`htb post <endpoint> key=value... [--data '{"json":...}']`.

## Notes

- After solving, re-run the explore command — the item drops from
  `status=incompleted` once owned.
- `chal start` output includes the target `ip`/`port` in its message; grab it with
  `--pick message` if needed.
- Never brute force flags. Solve the challenge, then submit the real flag once.
- Respect HTB rules; only interact with items on the authenticated account.
