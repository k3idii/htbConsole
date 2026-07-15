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
# Challenges — 
#  state=active  ->  ative, free ; 
#  status=incompleted -> UNSOLVED (default list mixes solved in)
htb chal list state=active status=incompleted per_page=10
htb chal list state=active status=incompleted per_page=10 page=2   # paginate
htb chal categories                                   # category id/name map

# Machines — no server-side unsolved filter; check the owns flags per item
htb machine list per_page=20        # unsolved = authUserInUserOwns / authUserInRootOwns false (--raw to see them)
htb machine retired per_page=20
htb machine active                  # what's running now
htb active                          # quick active machine check (shortcut)

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
htb chal start <id>                # spawn container -> returns message
htb chal start <id> --wait         # spawn + poll until ready -> returns {ip, ports}
htb chal stop  <id>

# Machines (VM management)
htb machine spawn <id>             # spawn VM -> returns message (also: machine start <id>)
htb machine spawn <id> --wait      # spawn + poll until IP ready -> returns {id, name, ip, ...}
htb machine terminate [id]         # stop VM (omit id = targets active VM; also: machine stop [id])
htb machine reset [id]             # reset VM (omit id = targets active VM)

# Submit flags / answers
htb chal submit <id> HTB{...}
htb machine submit <id> HTB{...}                  # user or root flag
htb sherlock submit <sherlock-id> <task-id> <answer>
```

Any endpoint not wrapped by a named command is reachable via
`htb post <endpoint> key=value... [--data '{"json":...}']`.

## Notes

## Common HTB Sherlock Zip Passwords
- PASSWORDS: `hackthebox` (default), `hacktheblue` (sherlocks)
- When listing tasks, do not fetch more then 5
- When starting containers/machines - use max 1 (ONE) at time
- After solving, re-run the explore command — the item drops from
  `status=incompleted` once owned.
- `--wait` on `chal start` or `machine spawn`: polls every 5s (max 3min) until
  ready, then prints IP (+ ports for challenges). Progress on stderr, result on stdout.
- Without `--wait`, `chal start` returns just the action message; grab ip with
  `--pick message` if needed.
- Never brute force flags. Solve the challenge, then submit the real flag once.
- Respect HTB rules; only interact with items on the authenticated account.
- Always write full step-by-step solution to `SOLVE.md` and try to create genealized skill that might impove solvin similar tasks in future into `SKILL.md`
- Always save all exploits,tools, notes and others files related to solved task following scheme :
   `./machines/{name}/`
   `./challenges/{category:uppercase}/{difficulty}__{name}/`
   `./sherlocks/{name}/`

   