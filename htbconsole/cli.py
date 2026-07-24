"""One-shot CLI for htbConsole — reuse the same API + settings without the TUI.

The API sessions (`HTBApiSession`, `HTBCTFSession`) are UI-agnostic. Here we set
their log hooks to plain stderr printers (only with ``--debug``), run a single
request, and print the minimal useful fields as YAML (``--raw`` for full JSON).

Commands are organized as a tree of :class:`Dispatcher` subclasses: each level pops
one word and calls ``handle_<word>``. A handler is tagged either ``@subcommand(child)``
(delegates to a nested Dispatcher) or ``@cmddoc(desc)`` and returns a
``(awaitable, shape)`` pair — the ``api.<method>(...)`` coroutine plus a minimal-fields
reducer. :func:`main` awaits the coroutine; the usage listing is built by exploring the
tagged ``handle_*`` methods (see :func:`_iter_commands`).

Usage:
    htbconsole cli <htb|ctf> <command...> [args] [key=value...] [options]

HTB read:
    htbconsole cli htb machine profile Fries
    htbconsole cli htb chal list per_page=50 state=retired difficulty[]=easy   # list filtering
    htbconsole cli htb user --pick info.name

HTB submit flag:
    htbconsole cli htb chal submit 123 HTB{...}
    htbconsole cli htb machine submit 808 HTB{...}
    htbconsole cli htb sherlock submit 42 3 my-answer          # <sherlock-id> <task-id> <answer>

CTF:
    htbconsole cli ctf list
    htbconsole cli ctf 1434 info
    htbconsole cli ctf 1434 list categories
    htbconsole cli ctf 1434 list tasks category=Web solved=false
    htbconsole cli ctf 1434 task 9876
    htbconsole cli ctf 1434 submit 9876 HTB{...}

Generic escape hatch (raw POST, any endpoint):
    htbconsole cli htb post /api/v4/challenge/own challenge_id=123 flag=HTB{...}
    htbconsole cli ctf post /api/flags/own --data '{"challenge_id":9876,"flag":"HTB{...}"}'
"""
import argparse
import asyncio
import json
import os
import re
import sys

from .appSettings import HTBSettings, CTFSettings
from .httpApi import HTBSession, HTBApiSession, HTBCTFSession

TOKEN_ENV = {"htb": "HTB_TOKEN", "ctf": "CTF_TOKEN"}


# --- logging handlers (just print to stderr; wired onto the session) --------

def _log_event(message):
    sys.stderr.write(f"[event] {message}\n")


def _log_debug(message, *args, **kwargs):
    extra = ""
    if args:
        extra += " " + " ".join(str(a) for a in args)
    if kwargs:
        extra += " " + str(kwargs)
    sys.stderr.write(f"[debug] {message}{extra}\n")


def _log_notify(message, severity="information", timeout=5):
    sys.stderr.write(f"[notify] {message} ({severity})\n")


# --- plan helpers -----------------------------------------------------------

def _params(base, kv):
    """Merge page/per_page tuples (*base* list) with key=value filters (*kv* dict)."""
    return list(base) + list(kv.items())


# --- output shaping: keep only the minimal useful fields per command --------

def _pick(d, keys):
    return {k: d.get(k) for k in keys if isinstance(d, dict) and k in d}


def _data(d):
    if isinstance(d, dict):
        return d.get("data") or []
    return d if isinstance(d, list) else []


def _meta(d):
    m = d.get("meta", {}) if isinstance(d, dict) else {}
    return _pick(m, ["current_page", "last_page", "per_page", "total"]) or None


def _shape_action(d):
    """Shared reducer for mutating actions (start/stop/submit): status-ish fields."""
    return (_pick(d, ["message", "success", "id", "status"]) or d) if isinstance(d, dict) else d


# --- directory setup helpers ------------------------------------------------

_SAFE_RE = re.compile(r'[^a-z0-9]')


def _safe(name):
    return _SAFE_RE.sub('_', name.lower()).strip('_')


def _mksetup(path):
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)


def _write_task_md(path, info, kind):
    """Write task.md with challenge/machine/sherlock metadata into *path*."""
    dest = os.path.join(path, "task.md")
    if os.path.exists(dest):
        sys.stderr.write(f"[setup] task.md already exists\n")
        return dest

    lines = []
    name = info.get("name", "?")

    if kind == "challenge":
        lines.append(f"# {name}\n")
        lines.append(f"- **Type**: Challenge")
        lines.append(f"- **Category**: {info.get('category_name', '?')}")
        lines.append(f"- **Difficulty**: {info.get('difficulty', '?')}")
        lines.append(f"- **Solves**: {info.get('solves', '?')}")
        lines.append(f"- **State**: {info.get('state', '?')}")
        lines.append(f"- **Play Methods**: {', '.join(info.get('play_methods') or ['?'])}")
        desc = info.get("description", "")
        if desc:
            lines.append(f"\n## Description\n\n{desc}")

    elif kind == "machine":
        lines.append(f"# {name}\n")
        lines.append(f"- **Type**: Machine")
        lines.append(f"- **OS**: {info.get('os', '?')}")
        lines.append(f"- **Difficulty**: {info.get('difficultyText', '?')}")
        lines.append(f"- **Points**: {info.get('points', '?')}")
        lines.append(f"- **Rating**: {info.get('stars', info.get('star', '?'))}")
        release = info.get("release", "")
        if release:
            lines.append(f"- **Release**: {release[:10]}")
        maker = (info.get("maker") or {}).get("name")
        if maker:
            makers = maker
            maker2 = (info.get("maker2") or {}).get("name")
            if maker2:
                makers += f", {maker2}"
            lines.append(f"- **Maker**: {makers}")
        lines.append(f"- **User Owns**: {info.get('user_owns_count', '?')}")
        lines.append(f"- **Root Owns**: {info.get('root_owns_count', '?')}")
        synopsis = info.get("synopsis", "")
        if synopsis:
            lines.append(f"\n## Description\n\n{synopsis}")

    elif kind == "sherlock":
        lines.append(f"# {name}\n")
        lines.append(f"- **Type**: Sherlock")
        lines.append(f"- **Category**: {info.get('category_name', '?')}")
        lines.append(f"- **Difficulty**: {info.get('difficulty', '?')}")
        lines.append(f"- **Solves**: {info.get('user_owns_count', info.get('solves', '?'))}")
        lines.append(f"- **Rating**: {info.get('rating', '?')}")
        lines.append(f"- **State**: {info.get('state', '?')}")

    text = "\n".join(lines) + "\n"
    with open(dest, "w") as f:
        f.write(text)
    sys.stderr.write(f"[setup] wrote task.md\n")
    return dest


def _extract_zip(zip_path, dest_dir):
    import zipfile
    passwords = [None, b"hackthebox", b"hacktheblue"]
    with zipfile.ZipFile(zip_path, "r") as zf:
        for pwd in passwords:
            try:
                zf.extractall(dest_dir, pwd=pwd)
                return len(zf.namelist())
            except (RuntimeError, Exception):
                continue
    raise RuntimeError(f"Cannot extract {zip_path} — tried passwords: none, hackthebox, hacktheblue")


async def _setup_chal(api, chal_id):
    data = await api.api_htb_chal_info(chal_id)
    c = data.get("challenge", {}) if isinstance(data, dict) else {}
    name = _safe(c.get("name", f"id_{chal_id}"))
    cat = _safe(c.get("category_name", "unknown"))
    diff = _safe(c.get("difficulty", "unknown"))
    path = _mksetup(os.path.join("challenges", cat, f"{diff}__{name}"))
    _write_task_md(path, c, "challenge")
    result = {"path": path}

    has_download = "download" in (c.get("play_methods") or [])
    if not has_download:
        result["download"] = None
        result["extracted"] = 0
        return result

    file_name = c.get("file_name") or f"challenge_{chal_id}.zip"
    zip_dest = os.path.join(path, file_name)
    result["download"] = file_name

    if not os.path.exists(zip_dest):
        dl_data = await api.api_htb_chal_download_link(chal_id)
        url = dl_data.get("url") if isinstance(dl_data, dict) else None
        if url:
            from .tuiComponents.downloader import async_download
            await async_download(url, zip_dest, headers=api.headers)
            sys.stderr.write(f"[setup] downloaded {file_name}\n")
        else:
            sys.stderr.write(f"[setup] no download url available\n")
            result["extracted"] = 0
            return result
    else:
        sys.stderr.write(f"[setup] {file_name} already exists\n")

    extract_dir = os.path.join(path, "extracted")
    if os.path.isdir(extract_dir) and os.listdir(extract_dir):
        count = len(os.listdir(extract_dir))
        sys.stderr.write(f"[setup] already extracted ({count} files)\n")
        result["extracted"] = count
    else:
        os.makedirs(extract_dir, exist_ok=True)
        count = _extract_zip(zip_dest, extract_dir)
        sys.stderr.write(f"[setup] extracted {count} files\n")
        result["extracted"] = count

    return result


async def _setup_machine(api, name_or_id):
    data = await api.api_htb_machine_profile(name_or_id)
    m = data.get("info", {}) if isinstance(data, dict) else {}
    name = _safe(m.get("name", f"id_{name_or_id}"))
    path = _mksetup(os.path.join("machines", name))
    _write_task_md(path, m, "machine")
    return {"path": path}


async def _setup_sherlock(api, sherlock_id):
    data = await api.api_htb_sherlock_info(sherlock_id)
    s = data.get("data", {}) if isinstance(data, dict) else {}
    name = _safe(s.get("name", f"id_{sherlock_id}"))
    path = _mksetup(os.path.join("sherlocks", name))
    _write_task_md(path, s, "sherlock")
    return {"path": path}


# --- arg + output helpers ---------------------------------------------------

def _split_args(words):
    """Separate bare positional args from ``key=value`` params."""
    result={}
    for tok in words:
        if "=" in tok:
            k, v = tok.split("=", 1)
            #if k.endswith("[]"):
            #    k = k[:-2]
            #    v = v.split(",")
            result[k]=v
        else:
            result[tok]=''
    return result


def _one(words, label):
    if len(words) != 1:
        raise ValueError(f"{label}: needs 1 arg, got {len(words)}")
    return words[0]


def _n(words, n, label):
    """Exactly *n* positionals, taken literally (flags may contain '=')."""
    if len(words) != n:
        raise ValueError(f"{label}: needs {n} arg(s), got {len(words)}")
    return words


def _drill(data, pick):
    for part in pick.split("."):
        if isinstance(data, list) and part.lstrip("-").isdigit():
            try:
                data = data[int(part)]
            except IndexError:
                return None
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def _emit(data, use_yaml, pick):
    if pick:
        data = _drill(data, pick)
    if use_yaml:
        import yaml
        sys.stdout.write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    else:
        sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _filter_items(items, params):
    """Client-side filter of a list of dicts by key=value (used for CTF tasks)."""
    for k, v in params:
        if k == "category":
            items = [c for c in items
                     if c.get("category", "").lower() == v.lower()]
        elif k == "solved":
            want = v.lower() in ("1", "true", "yes")
            items = [c for c in items if bool(c.get("solved")) == want]
        else:
            items = [c for c in items if str(c.get(k)).lower() == v.lower()]
    return items


# --- wait-for-ready helpers (spawn/start + poll) ---------------------------

_POLL_INTERVAL = 5
_POLL_MAX = 36  # 36 * 5s = 3 min


async def _spawn_machine_wait(api, machine_id):
    rsp = await api.api_htb_vm_spawn(machine_id)
    msg = rsp.get("message", "") if isinstance(rsp, dict) else ""
    sys.stderr.write(f"[wait] spawn: {msg}\n")
    for attempt in range(_POLL_MAX):
        await asyncio.sleep(_POLL_INTERVAL)
        data = await api.api_htb_machine_active(cache_this=0)
        info = data.get("info") if isinstance(data, dict) else None
        if info and info.get("ip"):
            sys.stderr.write(f"[wait] ready ({(attempt + 1) * _POLL_INTERVAL}s)\n")
            return _pick(info, ["id", "name", "ip", "type", "os", "expires_at"])
        sys.stderr.write(f"[wait] polling... ({(attempt + 1) * _POLL_INTERVAL}s)\n")
    return {"error": "timeout waiting for machine IP", "last_response": rsp}


async def _start_chal_wait(api, chal_id):
    rsp = await api.api_htb_chal_start(chal_id)
    msg = rsp.get("message", "") if isinstance(rsp, dict) else ""
    sys.stderr.write(f"[wait] start: {msg}\n")
    for attempt in range(_POLL_MAX):
        await asyncio.sleep(_POLL_INTERVAL)
        data = await api.api_htb_chal_info(chal_id, cache_this=0)
        play = (data.get("challenge", {}) or {}).get("play_info") if isinstance(data, dict) else None
        if isinstance(play, dict) and play.get("status") == "ready":
            sys.stderr.write(f"[wait] ready ({(attempt + 1) * _POLL_INTERVAL}s)\n")
            return {"ip": play.get("ip"), "ports": play.get("ports")}
        sys.stderr.write(f"[wait] polling... ({(attempt + 1) * _POLL_INTERVAL}s)\n")
    return {"error": "timeout waiting for container", "last_response": rsp}


# --- composite operations (multi-step; async, take the live api) ------------

async def _ctf_tasks(api, ctf_id, filters):
    challs = await api.api_ctf_challenges(ctf_id)
    return _filter_items(challs, filters)


async def _ctf_categories(api, ctf_id, full=False):
    cats_raw = await api.api_ctf_categories()
    cat_map = {}
    if isinstance(cats_raw, list):
        for cat in cats_raw:
            cid = cat.get("id", 0)
            cat_map[cid] = {"id": cid, "name": cat.get("name", f"Unknown-{cid}"),
                            "total": 0, "solved": 0}
    challs = await api.api_ctf_challenges(ctf_id)
    for c in challs:
        cid = c.get("challenge_category_id", 0)
        e = cat_map.setdefault(cid, {"id": cid,
                                     "name": c.get("category", f"Unknown-{cid}"),
                                     "total": 0, "solved": 0})
        e["total"] += 1
        if c.get("solved"):
            e["solved"] += 1
        if full:
            e.setdefault("challenges", []).append(
                _pick(c, ["id", "name", "difficulty", "solved", "points"]))
    used = [v for v in cat_map.values() if v["total"] > 0]
    return sorted(used, key=lambda x: x["name"])


async def _ctf_task(api, ctf_id, task_id):
    challs = await api.api_ctf_challenges(ctf_id)
    for c in challs:
        if str(c.get("id")) == str(task_id):
            return c
    return {"error": f"task {task_id} not found in CTF {ctf_id}"}


async def _start_ctf_task_wait(api, ctf_id, task_id):
    try:
        rsp = await api.api_ctf_task_start(task_id)
        msg = rsp.get("message", "") if isinstance(rsp, dict) else ""
    except Exception as e:
        msg = str(e)
        rsp = {"message": msg}
    sys.stderr.write(f"[wait] start: {msg}\n")
    for attempt in range(_POLL_MAX):
        await asyncio.sleep(_POLL_INTERVAL)
        detail = await api.api_ctf_info(ctf_id, cache_this=0)
        for c in detail.get("challenges", []):
            if c.get("id") == int(task_id):
                if c.get("docker_online") and c.get("hostname"):
                    ip = c["hostname"]
                    ports = c.get("docker_ports", [])
                    sys.stderr.write(f"[wait] ready ({(attempt + 1) * _POLL_INTERVAL}s)\n")
                    return {"ip": ip, "ports": ports}
                break
        sys.stderr.write(f"[wait] polling... ({(attempt + 1) * _POLL_INTERVAL}s)\n")
    return {"error": "timeout waiting for container", "last_response": rsp}


async def _setup_ctf_task(api, ctf_id, task_id):
    detail = await api.api_ctf_info(ctf_id)
    ctf_name = _safe(detail.get("name", f"id_{ctf_id}"))
    start = (detail.get("starts_at") or "0000-00")[:7]
    ctf_dir = f"{start}__{ctf_id}__{ctf_name}"

    task = await _ctf_task(api, ctf_id, task_id)
    if "error" in task:
        return task

    cat = _safe(task.get("category", "unknown"))
    diff = _safe(task.get("difficulty", "unknown"))
    tname = _safe(task.get("name", f"id_{task_id}"))
    task_dir = f"{cat}_{diff}__{tname}"

    path = _mksetup(os.path.join("ctfs", ctf_dir, task_dir))
    _write_task_md(path, {**task, "category_name": task.get("category", "?")}, "challenge")

    file_name = task.get("filename")
    result = {"path": path}
    if not file_name:
        return result

    zip_dest = os.path.join(path, file_name)
    result["download"] = file_name
    if not os.path.exists(zip_dest):
        try:
            data = await api.api_ctf_download(task_id)
            if data:
                with open(zip_dest, "wb") as f:
                    f.write(data)
                sys.stderr.write(f"[setup] downloaded {file_name}\n")
        except Exception as e:
            sys.stderr.write(f"[setup] download failed: {e}\n")
            return result
    else:
        sys.stderr.write(f"[setup] {file_name} already exists\n")

    extract_dir = os.path.join(path, "extracted")
    if os.path.isdir(extract_dir) and os.listdir(extract_dir):
        count = len(os.listdir(extract_dir))
        sys.stderr.write(f"[setup] already extracted ({count} files)\n")
        result["extracted"] = count
    else:
        os.makedirs(extract_dir, exist_ok=True)
        count = _extract_zip(zip_dest, extract_dir)
        sys.stderr.write(f"[setup] extracted {count} files\n")
        result["extracted"] = count

    return result


def _resolve_out(out_path, default_name):
    """Turn *out_path* into a concrete file path, creating parent dirs.

    A directory (existing or trailing-slash) gets *default_name* appended.
    """
    dest = os.path.expanduser(out_path)
    if os.path.isdir(dest) or dest.endswith(os.sep):
        os.makedirs(dest, exist_ok=True)
        dest = os.path.join(dest, default_name)
    else:
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
    return dest


async def _download_chal(api, cid, out_path):
    """GET the challenge download link, then save the zip to *out_path*."""
    data = await api.api_htb_chal_download_link(cid)
    url = data.get("url") if isinstance(data, dict) else None
    if not url:
        return {"error": "no download url in response", "response": data}
    from .tuiComponents.downloader import async_download
    dest = _resolve_out(out_path, f"challenge_{cid}.zip")
    size = await async_download(url, dest, headers=api.headers)
    return {"saved": os.path.abspath(dest), "bytes": size, "url": url}


async def _download_sherlock(api, sid, out_path):
    """GET the sherlock download link, then save the zip to *out_path*."""
    data = await api.api_htb_sherlock_download_link(sid)
    url = data.get("url") if isinstance(data, dict) else None
    if not url:
        return {"error": "no download url in response", "response": data}
    from .tuiComponents.downloader import async_download
    dest = _resolve_out(out_path, f"sherlock_{sid}.zip")
    size = await async_download(url, dest, headers=api.headers)
    return {"saved": os.path.abspath(dest), "bytes": size, "url": url}


def _generic_post(api, words, data_json):
    """`post <endpoint> [key=value...] [--data JSON]` -> raw POST coroutine."""
    if not words:
        raise ValueError("post: needs an endpoint, e.g. post /api/... key=value")
    path = words[0]
    body = dict(_split_args(words[1:]))
    if data_json:
        body.update(json.loads(data_json))
    return api.async_post(path, body)


# --- dispatcher tree --------------------------------------------------------

def subcommand(child_name):
    """Decorate a handler that delegates to a nested Dispatcher class (by name).

    The wrapper performs the delegation; the tag ``_subcommand`` lets the command
    explorer descend into *child_name* when building the usage listing.
    """
    def deco(fn):
        def wrapper(self, words, **kw):
            return globals()[child_name](self.api, words, **kw).result
        wrapper._subcommand = child_name
        wrapper.__name__ = getattr(fn, "__name__", child_name)
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return deco


def cmddoc(description):
    """Decorate a leaf handler that returns data, with a one-line help description."""
    def deco(fn):
        fn._cmddoc = description
        return fn
    return deco


class Dispatcher:
    """Pop the first word, call ``handle_<word>(words, **kw)``; store in ``self.result``.

    Every ``handle_*`` either is tagged ``@subcommand(child)`` (delegates to a nested
    Dispatcher) or ``@cmddoc(desc)`` and returns a ``(awaitable, shape)`` pair — the
    ``self.api.<method>(...)`` coroutine (or a composite coroutine) plus a minimal-fields
    reducer (or ``None``). *words* is a mutable list consumed as it descends the tree.
    """

    LABEL = "cli"

    def __init__(self, api: HTBSession, words, **kw):
        self.api: HTBSession = api
        self.result = self.dispatch(words, **kw)

    def dispatch(self, words, **kw):
        if not words:
            return self.default(**kw)
        cmd = words.pop(0)
        fn = getattr(self, f"handle_{cmd}", None)
        if fn is None:
            raise ValueError(f"{self.LABEL}: unknown command '{cmd}'")
        return fn(words, **kw)

    def default(self, **kw):
        raise ValueError(f"{self.LABEL}: missing subcommand")


class _MainCmd(Dispatcher):
    LABEL = "cli"

    @subcommand("_HtbCmd")
    def handle_htb(self, words, **kw): ...

    @subcommand("_CtfCmd")
    def handle_ctf(self, words, **kw): ...


class _HtbCmd(Dispatcher):
    LABEL = "htb"

    @subcommand("_ChalCmd")
    def handle_chal(self, words, **kw): ...

    @subcommand("_SherlockCmd")
    def handle_sherlock(self, words, **kw): ...

    @subcommand("_MachineCmd")
    def handle_machine(self, words, **kw): ...

    @subcommand("_SeasonCmd")
    def handle_season(self, words, **kw): ...

    @cmddoc("current user info")
    def handle_user(self, words, params, **kw):
        def shape(d):
            i = d.get("info", {}) if isinstance(d, dict) else {}
            out = _pick(i, ["id", "name", "email", "isVip", "subscriptionType", "rank_id"])
            if isinstance(i.get("team"), dict):
                out["team"] = i["team"].get("name")
            return out
        return self.api.api_htb_user_info(params), shape

    handle_me = handle_user

    @cmddoc("public profile by <uid>")
    def handle_profile(self, words, params, **kw):
        uid = _one(words, "htb profile")
        def shape(d):
            p = d.get("profile", {}) if isinstance(d, dict) else {}
            out = _pick(p, ["id", "name", "rank", "ranking", "points", "user_owns",
                            "system_owns", "user_bloods", "system_bloods", "country_name"])
            if isinstance(p.get("team"), dict):
                out["team"] = p["team"].get("name")
            return out
        return self.api.api_htb_profile(uid, params), shape

    @cmddoc("currently active machine")
    def handle_active(self, words, params, **kw):
        def shape(d):
            info = d.get("info") if isinstance(d, dict) else None
            if not info:
                return {"active": None}
            return _pick(info, ["id", "name", "ip", "type", "expires_at"])
        return self.api.api_htb_machine_active(params), shape

    @cmddoc("raw POST <endpoint> [key=value...] [--data JSON]")
    def handle_post(self, words, data_json=None, **kw):
        return _generic_post(self.api, words, data_json), None


class _ChalCmd(Dispatcher):
    LABEL = "chal"

    @cmddoc("list challenges [state= difficulty[]= category[]= per_page= page=]")
    def handle_list(self, words, **kw):
        kv = _split_args(words)
        def shape(d):
            fields = ["id", "name", "difficulty", "category_name", "state",
                      "solves", "is_owned", "rating", "release_date"]
            return {"challenges": [_pick(c, fields) for c in _data(d)], "meta": _meta(d)}
        return self.api.api_htb_chal_list(kv), shape

    @cmddoc("challenge info <id>")
    def handle_info(self, words, params, **kw):
        cid = _one(words, "chal info")
        def shape(d):
            c = d.get("challenge", {}) if isinstance(d, dict) else {}
            return _pick(c, ["id", "name", "category_name", "difficulty", "points", "solves",
                             "stars", "state", "retired", "release_date", "creator_name",
                             "download", "file_name", "file_size", "authUserSolve", "description"])
        return self.api.api_htb_chal_info(cid, params), shape

    @cmddoc("list challenge categories")
    def handle_categories(self, words, params, **kw):
        def shape(d):
            return [_pick(c, ["id", "name"]) for c in (d.get("info", []) if isinstance(d, dict) else [])]
        return self.api.api_htb_chal_categories(params), shape

    @cmddoc("community writeups <id>")
    def handle_writeup(self, words, params, **kw):
        cid = _one(words, "chal writeup")
        def shape(d):
            off = (d.get("data", {}) or {}).get("official") if isinstance(d, dict) else None
            if isinstance(off, dict):
                return {"official": _pick(off, ["filename", "url", "video_url"])}
            return d.get("data", d) if isinstance(d, dict) else d
        return self.api.api_htb_chal_writeup(cid, params), shape

    @cmddoc("zip download link <id> (url + expiry, no fetch)")
    def handle_link(self, words, params, **kw):
        cid = _one(words, "chal link")
        def shape(d):
            return _pick(d, ["url", "expires_in"]) if isinstance(d, dict) else d
        return self.api.api_htb_chal_download_link(cid, params), shape

    @cmddoc("fetch + save zip: download <id> <path>")
    def handle_download(self, words, **kw):
        cid, path = _n(words, 2, "chal download")
        return _download_chal(self.api, cid, path), None

    @cmddoc("start challenge container <id> [--wait: poll until IP:port ready]")
    def handle_start(self, words, **kw):
        cid = _one(words, "chal start")
        if kw.get("wait"):
            return _start_chal_wait(self.api, cid), None
        return self.api.api_htb_chal_start(cid), _shape_action

    @cmddoc("stop challenge container <id>")
    def handle_stop(self, words, **kw):
        cid = _one(words, "chal stop")
        return self.api.api_htb_chal_stop(cid), _shape_action

    @cmddoc("create working dir: setup <id>")
    def handle_setup(self, words, **kw):
        cid = _one(words, "chal setup")
        return _setup_chal(self.api, cid), None

    @cmddoc("submit flag <id> <flag>")
    def handle_submit(self, words, **kw):
        cid, flag = _n(words, 2, "chal submit")
        return self.api.api_htb_chal_submit(cid, flag), _shape_action


class _SherlockCmd(Dispatcher):
    LABEL = "sherlock"

    @cmddoc("list sherlocks [per_page= page=]")
    def handle_list(self, words, params, **kw):
        kv = _split_args(words)
        def shape(d):
            fields = ["id", "name", "difficulty", "category_name", "state",
                      "solves", "is_owned", "progress", "rating", "release_date"]
            return {"sherlocks": [_pick(s, fields) for s in _data(d)], "meta": _meta(d)}
        return self.api.api_htb_sherlock_list(_params(params, kv)), shape

    @cmddoc("sherlock info <id>")
    def handle_info(self, words, params, **kw):
        sid = _one(words, "sherlock info")
        def shape(d):
            s = d.get("data", {}) if isinstance(d, dict) else {}
            out = _pick(s, ["id", "description", "user_owns_count"])
            mods = s.get("academyModules") or []
            if mods:
                out["academyModules"] = [m.get("name") for m in mods if isinstance(m, dict)]
            return out
        return self.api.api_htb_sherlock_info(sid, params), shape

    @cmddoc("sherlock tasks <id>")
    def handle_tasks(self, words, params, **kw):
        sid = _one(words, "sherlock tasks")
        def shape(d):
            return [_pick(t, ["id", "title", "description", "completed", "masked_flag"])
                    for t in _data(d)]
        return self.api.api_htb_sherlock_tasks(sid, params), shape

    @cmddoc("sherlock download link <id> (url + expiry, no fetch)")
    def handle_link(self, words, params, **kw):
        sid = _one(words, "sherlock link")
        def shape(d):
            return _pick(d, ["url", "expires_in"]) if isinstance(d, dict) else d
        return self.api.api_htb_sherlock_download_link(sid, params), shape

    @cmddoc("fetch + save sherlock zip: download <id> <path>")
    def handle_download(self, words, **kw):
        sid, path = _n(words, 2, "sherlock download")
        return _download_sherlock(self.api, sid, path), None

    @cmddoc("create working dir: setup <id>")
    def handle_setup(self, words, **kw):
        sid = _one(words, "sherlock setup")
        return _setup_sherlock(self.api, sid), None

    @cmddoc("submit answer <sherlock-id> <task-id> <answer>")
    def handle_submit(self, words, **kw):
        sid, tid, answer = _n(words, 3, "sherlock submit")
        return self.api.api_htb_sherlock_submit(sid, tid, answer), _shape_action


class _MachineCmd(Dispatcher):
    LABEL = "machine"

    _MACHINE_FIELDS = ["id", "name", "os", "difficultyText", "points", "star", "release",
                       "user_owns_count", "root_owns_count", "free", "active", "ip"]

    def _machine_list_shape(self, d):
        return {"machines": [_pick(m, self._MACHINE_FIELDS) for m in _data(d)], "meta": _meta(d)}

    @cmddoc("list active machines [per_page= page=]")
    def handle_list(self, words, params, **kw):
        kv = _split_args(words)
        return self.api.api_htb_machine_list(_params(params, kv)), self._machine_list_shape

    @cmddoc("list retired machines [per_page= page=]")
    def handle_retired(self, words, params, **kw):
        kv = _split_args(words)
        return self.api.api_htb_machine_retired(_params(params, kv)), self._machine_list_shape

    @cmddoc("currently active machine")
    def handle_active(self, words, params, **kw):
        def shape(d):
            info = d.get("info") if isinstance(d, dict) else None
            if not info:
                return {"active": None}
            return _pick(info, ["id", "name", "ip", "type", "expires_at"])
        return self.api.api_htb_machine_active(params), shape

    @cmddoc("machine profile <name>")
    def handle_profile(self, words, params, **kw):
        name = _one(words, "machine profile")
        def shape(d):
            m = d.get("info", {}) if isinstance(d, dict) else {}
            out = _pick(m, ["id", "name", "os", "difficultyText", "points", "active", "retired",
                            "release", "user_owns_count", "root_owns_count", "stars", "ip",
                            "info_status", "synopsis"])
            if isinstance(m.get("maker"), dict):
                out["maker"] = m["maker"].get("name")
            return out
        return self.api.api_htb_machine_profile(name, params), shape

    handle_info = handle_profile

    @cmddoc("submit flag <id> <flag>")
    def handle_submit(self, words, **kw):
        mid, flag = _n(words, 2, "machine submit")
        return self.api.api_htb_machine_submit(mid, flag), _shape_action

    @cmddoc("create working dir: setup <name>")
    def handle_setup(self, words, **kw):
        name = _one(words, "machine setup")
        return _setup_machine(self.api, name), None

    @cmddoc("spawn/start VM by <id> [--wait: poll until IP ready]")
    def handle_spawn(self, words, **kw):
        mid = _one(words, "machine spawn")
        if kw.get("wait"):
            return _spawn_machine_wait(self.api, mid), None
        return self.api.api_htb_vm_spawn(mid), _shape_action

    handle_start = handle_spawn

    async def _resolve_mid_or_active(self, words):
        if words:
            return words[0]
        active_data = await self.api.api_htb_machine_active()
        active_info = active_data.get("info") if isinstance(active_data, dict) else None
        if active_info and "id" in active_info:
            return str(active_info["id"])
        raise ValueError("No machine ID provided and no active machine found to target.")

    @cmddoc("terminate/stop active VM, or <id> if specified")
    def handle_terminate(self, words, **kw):
        async def run():
            mid = await self._resolve_mid_or_active(words)
            return await self.api.api_htb_vm_terminate(mid)
        return run(), _shape_action

    handle_stop = handle_terminate

    @cmddoc("reset active VM, or <id> if specified")
    def handle_reset(self, words, **kw):
        async def run():
            mid = await self._resolve_mid_or_active(words)
            return await self.api.api_htb_vm_reset(mid)
        return run(), _shape_action



class _SeasonCmd(Dispatcher):
    LABEL = "season"

    @cmddoc("list seasons")
    def handle_list(self, words, params, **kw):
        def shape(d):
            return [_pick(s, ["id", "name", "state", "active", "start_date", "end_date", "players"])
                    for s in _data(d)]
        return self.api.api_htb_season_list(params), shape


class _CtfCmd(Dispatcher):
    LABEL = "ctf"
    _ctx_child = "_CtfCtxCmd"  # a leading numeric word -> per-CTF context (for help)

    def dispatch(self, words, **kw):
        if words and words[0].isdigit():
            ctf_id = words.pop(0)
            return _CtfCtxCmd(self.api, words, ctf_id=ctf_id, **kw).result
        return super().dispatch(words, **kw)

    @cmddoc("list ongoing CTFs [page=N] [--full]")
    def handle_list(self, words, params, full=False, **kw):
        kv = _split_args(words)
        def shape(d):
            if not isinstance(d, list):
                return d
            fields = ["id", "name", "starts_at", "canJoin"]
            return [_pick(c, fields) for c in d]
        return self.api.api_ctf_list(_params(params, kv)), None if full else shape

    @cmddoc("list past CTFs [page=N]")
    def handle_past(self, words, params, **kw):
        kv = _split_args(words)
        return self.api.api_ctf_past(_params(params, kv)), None

    @cmddoc("raw POST <endpoint> [key=value...] [--data JSON]")
    def handle_post(self, words, data_json=None, **kw):
        return _generic_post(self.api, words, data_json), None


class _CtfCtxCmd(Dispatcher):
    """Per-CTF subcommands; needs ``ctf_id`` in kw."""

    LABEL = "ctf <id>"

    def default(self, ctf_id, params, **kw):
        def shape(d):
            if isinstance(d, dict):
                d.pop("challenges", None)
            return d
        return self.api.api_ctf_info(ctf_id, params), shape

    @cmddoc("CTF info (default)")
    def handle_info(self, words, ctf_id, params, **kw):
        return self.default(ctf_id=ctf_id, params=params, **kw)

    @cmddoc("CTF scoreboard")
    def handle_scores(self, words, ctf_id, params, **kw):
        return self.api.api_ctf_scores(ctf_id, params), None

    @cmddoc("list tasks [category= solved= difficulty=]")
    def handle_tasks(self, words, ctf_id, params, **kw):
        kv = _split_args(words)
        def shape(d):
            if not isinstance(d, list):
                return d
            return [_pick(c, ["id", "name", "category", "difficulty", "solved"]) for c in d]
        return _ctf_tasks(self.api, ctf_id, _params(params, kv)), shape

    @cmddoc("list categories [--full]")
    def handle_categories(self, words, ctf_id, full=False, **kw):
        return _ctf_categories(self.api, ctf_id, full=full), None

    handle_cat = handle_categories

    @cmddoc("task detail <task-id>")
    def handle_task(self, words, ctf_id, **kw):
        tid = _one(words, "ctf task")
        return _ctf_task(self.api, ctf_id, tid), None

    @cmddoc("create working dir: setup <task-id>")
    def handle_setup(self, words, ctf_id, **kw):
        tid = _one(words, "ctf setup")
        return _setup_ctf_task(self.api, ctf_id, tid), None

    @cmddoc("start task container <task-id> [--wait: poll until IP:port ready]")
    def handle_start(self, words, ctf_id, **kw):
        tid = _one(words, "ctf start")
        if kw.get("wait"):
            return _start_ctf_task_wait(self.api, ctf_id, tid), None
        return self.api.api_ctf_task_start(tid), _shape_action

    @cmddoc("stop task container <task-id>")
    def handle_stop(self, words, ctf_id, **kw):
        tid = _one(words, "ctf stop")
        return self.api.api_ctf_task_stop(tid), _shape_action

    @cmddoc("submit flag <task-id> <flag>")
    def handle_submit(self, words, ctf_id, **kw):
        tid, flag = _n(words, 2, "ctf submit")
        return self.api.api_ctf_submit(tid, flag), None


def _iter_commands(cls, prefix):
    """Explore *cls*'s ``handle_*``: descend ``@subcommand``, list ``@cmddoc`` leaves."""
    seen = set()
    for name, fn in vars(cls).items():
        if not name.startswith("handle_"):
            continue
        if id(fn) in seen:
            continue
        seen.add(id(fn))
        cmd = name[len("handle_"):]
        child = getattr(fn, "_subcommand", None)
        doc = getattr(fn, "_cmddoc", None)
        if child:
            yield from _iter_commands(globals()[child], prefix + [cmd])
        elif doc is not None:
            yield " ".join(prefix + [cmd]), doc
    ctx = getattr(cls, "_ctx_child", None)
    if ctx:
        yield from _iter_commands(globals()[ctx], prefix + ["<id>"])


def _usage_commands():
    rows = list(_iter_commands(_MainCmd, ["cli"]))
    width = max((len(path) for path, _ in rows), default=0)
    lines = [f"  htbconsole {path.ljust(width)}   {desc}" for path, desc in rows]
    return "commands:\n" + "\n".join(lines)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="htbconsole cli",
        description="One-shot htbConsole API query / action. Prints minimal fields as YAML; use --raw for full JSON.",
        epilog=_usage_commands(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--raw", action="store_true", help="full raw JSON response (default: minimal fields as YAML)")
    parser.add_argument("--pick", help="drill into result by dotted path, e.g. info.name or 0.id")
    parser.add_argument("--data", help="extra JSON object merged into a POST body")
    parser.add_argument("--page", help="convenience query param: page=N")
    parser.add_argument("--per-page", dest="per_page", help="convenience query param: per_page=N")
    parser.add_argument("--token", help="API token (default: HTB_TOKEN / CTF_TOKEN env)")
    parser.add_argument("--wait", action="store_true",
                        help="after spawn/start, poll until the machine or container is ready and print IP (+ ports)")
    parser.add_argument("--full", action="store_true", help="show all fields instead of minimal summary")
    parser.add_argument("--debug", action="store_true", help="print API messages to stderr")
    parser.add_argument("words", nargs="*", help="<htb|ctf> <command...> [args] [key=value ...]")
    args = parser.parse_args(argv)

    words = args.words
    if not words:
        parser.print_help(sys.stderr)
        return 2

    platform = words[0].lower()
    if platform not in ("htb", "ctf"):
        sys.stderr.write(f"error: unknown platform '{platform}' (expected htb or ctf)\n")
        return 2

    params = []
    if args.page:
        params.append(("page", args.page))
    if args.per_page:
        params.append(("per_page", args.per_page))

    token = args.token or os.environ.get(TOKEN_ENV[platform], "")
    if not token:
        sys.stderr.write(f"error: no token — set {TOKEN_ENV[platform]} or pass --token\n")
        return 2

    settings = (HTBSettings if platform == "htb" else CTFSettings).load()
    session_cls = HTBApiSession if platform == "htb" else HTBCTFSession
    cache_file = os.path.join(settings.workdir, f"{platform}_cli_cache.json")
    api = session_cls(token, cache_file=cache_file)
    api.USE_CACHE = False
    if args.debug:
        api._handle_log_event = _log_event
        api._handle_log_debug = _log_debug
        api._handle_notify = _log_notify

    async def _run():
        try:
            result, shape = _MainCmd(api, list(words), params=params,
                                        data_json=args.data, wait=args.wait,
                                        full=args.full).result
            return await result, shape
        finally:
            await api.close()

    try:
        data, shape = asyncio.run(_run())
    except Exception as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    if not args.raw and shape:
        try:
            data = shape(data)
        except Exception:
            pass  # on any surprise shape, fall back to full data (still YAML)
    _emit(data, use_yaml=not args.raw, pick=args.pick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
