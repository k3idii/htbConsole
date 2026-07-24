---
name: htb-cli
description: Explore, select, and solve Hack The Box items (challenges, machines, sherlocks) from the terminal
---

# HTB via the htbconsole CLI

One-shot HTB API access. Prints **minimal fields as YAML** by default; add `--raw`
for the full JSON, `--pick <dotted.path>` to drill (e.g. `--pick 0.id`, `--pick info.name`).

## Setup

Needs an HTB API token in `HTB_TOKEN`. 
```bash
set -a; source ./token.txt; set +a      # exports HTB_TOKEN (+ CTF_TOKEN)
```
If token is missing - ask operator.

Invoke as `uvx htbconsole cli <cmd>` (or `htbconsole cli htb <cmd>` if installed).
Run `uvx htbconsole cli` with no args to see the full generated command list.

The examples below write **`htb`** as shorthand for `uvx htbconsole cli htb`
(optionally `alias htb='uvx htbconsole cli htb'`).

## Workflow: explore → select → solve

### 1. Explore (find unsolved work)

All list subcommands take per_page=N page=M parameters for pagination.

```bash
# Challenges — 
htb chal list state=active status=incompleted 
#  state=active  ->  ative, free ; 
#  status=incompleted -> UNSOLVED (default list mixes solved in)
htb chal categories                                   # category id/name map

# Machines — no server-side unsolved filter; check the owns flags per item
htb machine list
# unsolved = authUserInUserOwns / authUserInRootOwns false (--raw to see them)
htb machine retired
htb machine active                  # what's running now
htb active                          # quick active machine check (shortcut)

# Sherlocks (DFIR) — unsolved = is_owned false / progress < 100
htb sherlock list status=incompleted 
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
# Setup working directories (fetches info from API, creates dir)
htb chal setup <id>                # -> challenges/{category}/{difficulty}__{name}/ + download + extract
htb machine setup <name>           # -> machines/{name}/
htb sherlock setup <id>            # -> sherlocks/{name}/
# Output: {path, download, extracted} for chal; {path} for machine/sherlock

# Challenge files
htb chal link <id>                 # signed download URL (url + expiry), no download
htb chal download <id> <path>      # fetch + save the zip (path is REQUIRED)

# Challenge container (for pwn/web/etc. that need a live target)
htb chal start <id> [--wait]      # spawn + poll until ready -> returns {ip, ports}
htb chal stop  <id>

# Machines (VM management)
htb machine spawn <id> [--wait]      # spawn + poll until IP ready -> returns {id, name, ip, ...}
htb machine terminate [id]         # stop VM (omit id = targets active VM; also: machine stop [id])
htb machine reset [id]             # reset VM (omit id = targets active VM)

# Submit flags / answers
htb chal submit <id> HTB{...}
htb machine submit <id> HTB{...}                  # user or root flag
htb sherlock submit <sherlock-id> <task-id> <answer>
```

Any endpoint not wrapped by a named command is reachable via
`htb post <endpoint> key=value... [--data '{"json":...}']`.

## CTF Platform

Uses `CTF_TOKEN` (separate from `HTB_TOKEN`). Shorthand below: `ctf` = `uvx htbconsole cli ctf`.

### Browse CTFs

```bash
ctf list                          # ongoing/upcoming CTFs (minimal: id, name, starts_at, canJoin . use --full all fields (status, team, players, format, mcp_access_mode, etc.)
ctf past                          # past CTFs (paginated)
ctf <id> info                     # CTF detail (no challenges in output)
ctf <id> scores                   # scoreboard
```

### Tasks & Categories

```bash
ctf <id> categories               # category summary (id, name, total, solved)
ctf <id> categories --full        # categories + challenge list per category (id, name, difficulty, solved, points)
ctf <id> cat                      # alias for categories
ctf <id> tasks                    # all tasks (id, name, category, difficulty, solved)
# Filters : category=[Web,...]  solved=false - unsolved only, difficulty=[easy,medium,hard,insane] 
ctf <id> task <task-id>           # full task detail
```

### Solve

```bash
# Setup working directory (creates dir + downloads zip + extracts)
ctf <id> setup <task-id>
# -> ctfs/{YYYY-MM}__{ctf_id}__{ctf_name}/{category}_{difficulty}__{task_name}/
# Output: {path, download, extracted}

# Task container (for web/pwn challenges with docker)
ctf <id> start <task-id> [--wait]   # start container; --wait polls until IP:port ready -> {ip, ports}
ctf <id> stop <task-id>             # stop container

# Submit flag
ctf <id> submit <task-id> HTB{...}
```

## Common HTB Sherlock Zip Passwords
- if anything is missing or not clear ALWAYS ASK OPERATOR
- PASSWORDS: `hackthebox` (default), `hacktheblue` (sherlocks)

## Notes
- When listing tasks, do not fetch more then 5
- When starting containers/machines - use max 1 (ONE) at time
- After solving, re-run the explore command — the item drops from
  `status=incompleted` once owned.
- `--wait` on `chal start` or `machine spawn`: polls every 5s (max 3min) until
  ready, then prints IP (+ ports for challenges). Without `--wait` returns just the action message; grab ip with `--pick message` if needed.
- Never brute force flags.
- Solve the challenge, then submit the flag.
- Respect HTB rules; only interact with items on the authenticated account.
- Always write full step-by-step solution to `SOLVE.md`.
- After each step/command save short summary into `progress.md`.
- Try to load `SKILL.md` from category directory.
- Try to create genealized skill that might impove solvin similar tasks in future into `SKILL.md` in category directory
- Always create explit files/scripts rather then inline execution. Save all sub-certsion of exploits/toots. Always save all files related to solved task following scheme :
   `./machines/{name}/`
   `./challenges/{category}/{difficulty}__{name}/` 
   `./sherlocks/{name}/`
   `./ctfs/{YYYY-MM}__{ctf_id}__{ctf_name}/{category}_{difficulty}__{task_name}/`
   (all are LOWER CASE, a-z,0-9 only)
   