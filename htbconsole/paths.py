import os
import re

_SAFE_RE = re.compile(r'[^a-z0-9_]')


def _safe(name):
    return _SAFE_RE.sub('_', name.lower()).strip('_')


def _path_for_ctf(workdir, ctf_detail):
    """Return CTF base directory: {workdir}/ctfs/{YYYY-MM}__{id}__{name}"""
    start = (ctf_detail.get('starts_at') or '0000-00')[:7]
    ctf_id = ctf_detail.get('id', 0)
    ctf_name = _safe(ctf_detail.get('name', f'id_{ctf_id}'))
    return os.path.join(workdir, "ctfs", f"{start}__{ctf_id}__{ctf_name}")


def _path_for_ctf_task(workdir, ctf_detail, chall):
    """Return task directory: {ctf_path}/{cat}_{diff}__{name}"""
    base = _path_for_ctf(workdir, ctf_detail)
    cat = _safe(chall.get('category') or chall.get('category_name') or 'unknown')
    diff = _safe(chall.get('difficulty') or 'unknown')
    tname = _safe(chall.get('name', f"id_{chall.get('id', 0)}"))
    return os.path.join(base, f"{cat}_{diff}__{tname}")


def _path_for_challenge(workdir, chall):
    """Return HTB challenge directory: {workdir}/challenges/{cat}/{diff}__{name}"""
    cat = _safe(chall.get('category_name') or chall.get('category') or 'unknown')
    diff = _safe(chall.get('difficulty') or 'unknown')
    name = _safe(chall.get('name', f"id_{chall.get('id', 0)}"))
    return os.path.join(workdir, "challenges", cat, f"{diff}__{name}")


def _path_for_machine(workdir, machine):
    """Return HTB machine directory: {workdir}/machines/{name}"""
    name = _safe(machine.get('name', f"id_{machine.get('id', 0)}"))
    return os.path.join(workdir, "machines", name)


def _path_for_sherlock(workdir, sherlock):
    """Return HTB sherlock directory: {workdir}/sherlocks/{name}"""
    name = _safe(sherlock.get('name', f"id_{sherlock.get('id', 0)}"))
    return os.path.join(workdir, "sherlocks", name)
