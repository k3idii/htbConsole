import os
import re

from textual import on
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import (
    Label, TabbedContent, TabPane,
    DataTable, Static, Button, Input, Markdown
)
from textual.containers import Container, VerticalScroll, Horizontal

from rich.table import Table

from .messages import DebugMsg, ErrorMsg, EventMsg
from .downloader import execute_unpack
from .notes_editor import NotesEditor
from .confirm_dir import ensure_task_dir


CATEGORY_NAMES = {
    1: "Sanity", 2: "Pwn", 3: "Crypto", 4: "Misc", 5: "Web",
    6: "Stego", 7: "Forensics", 8: "Reversing", 9: "Mobile",
    10: "ML/AI", 11: "Blockchain", 12: "Coding", 13: "GamePwn",
    14: "OSINT", 15: "Hardware", 16: "Fullpwn", 17: "ICS",
    18: "Cloud", 19: "Defense", 20: "Attack", 21: "Cloud",
}


def _safe_dirname(name):
    return re.sub(r'[^\w\-. ]+', '_', name).strip('_. ')


def _ctf_base_dir(workdir, ctf_detail):
    start = (ctf_detail.get('starts_at') or '0000-00-00')[:10]
    ctf_id = ctf_detail.get('id', 0)
    return os.path.join(workdir, f"CTF_{start}__{ctf_id}")


def _task_dir(workdir, ctf_detail, chall):
    base = _ctf_base_dir(workdir, ctf_detail)
    cat_id = chall.get('challenge_category_id', 0)
    cat_name = _safe_dirname(CATEGORY_NAMES.get(cat_id, f"Unknown-{cat_id}"))
    task_name = _safe_dirname(chall.get('name', f"task_{chall['id']}"))
    return os.path.join(base, cat_name, f"{chall['id']}__{task_name}")


class ConfirmDirsScreen(ModalScreen):

    CSS = """
    ConfirmDirsScreen { align: center middle; }
    #confirm_dirs_dialog { width: 70%; height: auto; padding: 2; background: #1a2332; border: panel #3d5276; }
    #confirm_dirs_dialog Label { width: 100%; margin-bottom: 1; }
    #confirm_dirs_buttons { layout: horizontal; width: 100%; }
    #confirm_dirs_buttons Button { width: 1fr; }
    """

    def __init__(self, base_path, task_count):
        super().__init__()
        self._base_path = base_path
        self._task_count = task_count

    def compose(self) -> ComposeResult:
        with Container(id="confirm_dirs_dialog"):
            yield Label("[b]Create task directories[/b]")
            yield Label(f"Base path: {self._base_path}")
            yield Label(f"Tasks: {self._task_count}")
            yield Label("This will create category/task directories for all challenges.")
            with Horizontal(id="confirm_dirs_buttons"):
                yield Button("Create", id="confirm_yes", variant="success")
                yield Button("Cancel", id="confirm_no")

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "confirm_yes")


class CTFChallengesView(Container):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected_chall = None

    def compose(self) -> ComposeResult:
        with TabbedContent(id="ctf_context_tabs"):
            with TabPane("General", id="tab_ctf_general"):
                yield Static(id="ctf_general_info")
            with TabPane("Tasks", id="tab_ctf_tasks"):
                with Horizontal(id="ctf_chall_layout"):
                    with Container(id="ctf_cat_pane"):
                        yield DataTable(id="ctf_cat_table")
                        yield Button("Create dirs for all tasks", id="ctf_create_dirs_btn")
                    with Container(id="ctf_chall_pane"):
                        yield DataTable(id="ctf_chall_table")
                    with Container(id="ctf_detail_pane"):
                        with TabbedContent(id="ctf_detail_tabs"):
                            with TabPane("Info", id="tab_ctf_detail_info"):
                                with VerticalScroll(id="ctf_detail_scroll"):
                                    yield Markdown(id="ctf_chall_detail")
                                with Horizontal(id="ctf_action_buttons"):
                                    yield Button("Download", id="ctf_download_btn", variant="primary")
                                with Horizontal(id="ctf_flag_container"):
                                    yield Input(placeholder="Flag...", id="ctf_flag_input")
                                    yield Button("Submit", id="ctf_flag_submit")
                            with TabPane("Notes", id="tab_ctf_detail_notes"):
                                yield Label("Notes  <ctrl+s> to save", id="ctf_notes_label")
                                yield NotesEditor("", id="ctf_notes_editor")
            with TabPane("Ranking", id="tab_ctf_ranking"):
                yield Static(id="ctf_ranking_team_info")
                yield DataTable(id="ctf_ranking_table")
            with TabPane("Scoreboard", id="tab_ctf_scoreboard"):
                yield Static(id="ctf_scoreboard_info")
                yield DataTable(id="ctf_scoreboard_table")

    async def on_mount(self):
        cat_dt = self.query_one("#ctf_cat_table", DataTable)
        cat_dt.show_header = True
        cat_dt.cursor_type = "row"
        cat_dt.add_column(label="Category")
        cat_dt.add_column(label="Solved")

        chall_dt = self.query_one("#ctf_chall_table", DataTable)
        chall_dt.show_header = True
        chall_dt.cursor_type = "row"
        chall_dt.add_column(label="Name", width=20)
        chall_dt.add_column(label="Diff")
        chall_dt.add_column(label="Pts")
        chall_dt.add_column(label="Done")

        rank_dt = self.query_one("#ctf_ranking_table", DataTable)
        rank_dt.show_header = True
        rank_dt.cursor_type = "row"
        rank_dt.add_column(label="#", width=5)
        rank_dt.add_column(label="Challenge", width=20)
        rank_dt.add_column(label="Category")
        rank_dt.add_column(label="Points")
        rank_dt.add_column(label="Solves")
        rank_dt.add_column(label="You")

        sb_dt = self.query_one("#ctf_scoreboard_table", DataTable)
        sb_dt.show_header = True
        sb_dt.cursor_type = "row"
        sb_dt.add_column(label="#", width=5)
        sb_dt.add_column(label="Team", width=25)
        sb_dt.add_column(label="Country")
        sb_dt.add_column(label="Points")
        sb_dt.add_column(label="Flags")

    def load_ctf(self, ctf_data):
        self.run_worker(self._load_ctf(ctf_data))

    async def _load_ctf(self, ctf_data):
        try:
            detail = await self.app.CTF_API.get(f"/api/ctfs/{ctf_data['id']}")
            self.app._current_ctf = detail
            challenges = detail.get('challenges', [])
            self.app._ctf_challenges = {c['id']: c for c in challenges}

            team = detail.get('participating_team') or {}
            solved = sum(1 for c in challenges if c.get('solved'))

            gt = Table.grid(expand=True)
            gt.add_column(ratio=1)
            gt.add_column(ratio=2)
            gt.add_row("CTF", detail['name'])
            gt.add_row("Organizer", detail.get('org_name', '?'))
            gt.add_row("Status", detail.get('status', '?'))
            gt.add_row("Start", detail.get('starts_at', '?')[:16])
            gt.add_row("End", detail.get('ends_at', '?')[:16])
            gt.add_row("Team Size", str(detail.get('team_size', '?')))
            gt.add_row("", "")
            gt.add_row("[b]Team", team.get('name', '-'))
            gt.add_row("Members", str(team.get('participating_members', '-')))
            gt.add_row("Points", str(team.get('points', 0)))
            gt.add_row("Solved", f"{team.get('solved_challenges', solved)}/{len(challenges)}")
            gt.add_row("", "")
            gt.add_row("VPN", "Yes" if detail.get('hasVPN') else "No")
            gt.add_row("Pwnbox", "Yes" if detail.get('hasPwnbox') else "No")
            gt.add_row("MCP", detail.get('mcp_access_mode', '-'))
            gt.add_row("AI Policy", str(detail.get('ai_usage_policy') or '-'))
            gt.add_row("", "")
            gt.add_row("[b]Workdir", _ctf_base_dir(self.app.settings.workdir, detail))
            self.query_one("#ctf_general_info").update(gt)

            cats = {}
            for c in challenges:
                cat_id = c.get('challenge_category_id', 0)
                cat_name = CATEGORY_NAMES.get(cat_id, f"Unknown-{cat_id}")
                if cat_id not in cats:
                    cats[cat_id] = {'name': cat_name, 'total': 0, 'solved': 0, 'challenges': []}
                cats[cat_id]['total'] += 1
                if c.get('solved'):
                    cats[cat_id]['solved'] += 1
                cats[cat_id]['challenges'].append(c)

            self.app._ctf_cats = cats
            cat_dt = self.query_one("#ctf_cat_table", DataTable)
            cat_dt.clear()
            for cat_id, cat in sorted(cats.items(), key=lambda x: x[1]['name']):
                cat_dt.add_row(cat['name'], f"{cat['solved']}/{cat['total']}", key=cat_id)

            self.query_one("#ctf_chall_detail", Markdown).update("*Select a category, then a challenge*")
            self._selected_chall = None
            self._update_action_buttons()

            rt = Table.grid(expand=True)
            rt.add_column(ratio=1)
            rt.add_column(ratio=2)
            if team:
                rt.add_row("[b]Your Team", f"[b #9fef00]{team.get('name', '-')}")
                rt.add_row("Rank", f"#{team.get('rank', '?')}")
                rt.add_row("Points", str(team.get('points', 0)))
                rt.add_row("Solved", f"{team.get('solved_challenges', solved)}/{len(challenges)}")
                rt.add_row("Flags", f"{team.get('owned_flags', solved)}/{team.get('total_flags', len(challenges))}")
                rt.add_row("Members", str(team.get('participating_members', '?')))
            else:
                rt.add_row("Team", "Not participating")
            self.query_one("#ctf_ranking_team_info").update(rt)

            rank_dt = self.query_one("#ctf_ranking_table", DataTable)
            rank_dt.clear()
            sorted_challs = sorted(challenges, key=lambda c: c.get('solves', 0))
            for i, c in enumerate(sorted_challs, 1):
                cat_name = CATEGORY_NAMES.get(c.get('challenge_category_id', 0), '?')
                rank_dt.add_row(
                    str(i),
                    c['name'],
                    cat_name,
                    str(c.get('points', 0)),
                    str(c.get('solves', 0)),
                    "✅" if c.get('solved') else "❌",
                )

            await self._load_scoreboard(detail['id'], team)

        except Exception as e:
            self.app.post_message(ErrorMsg(e))

    async def _load_scoreboard(self, ctf_id, my_team):
        try:
            data = await self.app.CTF_API.get(f"/api/ctfs/scores/{ctf_id}")
            scores = data.get('scores', [])

            sb_info = Table.grid(expand=True)
            sb_info.add_column(ratio=1)
            sb_info.add_column(ratio=2)
            sb_info.add_row("Total Teams", str(data.get('ctf_teams', len(scores))))
            sb_info.add_row("Total Players", str(data.get('ctf_players', '?')))
            if my_team:
                my_rank = None
                for i, s in enumerate(scores, 1):
                    if s.get('id') == my_team.get('id'):
                        my_rank = i
                        break
                sb_info.add_row("Your Rank", f"#{my_rank or '?'} / {len(scores)}")
            self.query_one("#ctf_scoreboard_info").update(sb_info)

            sb_dt = self.query_one("#ctf_scoreboard_table", DataTable)
            sb_dt.clear()
            for i, team in enumerate(scores, 1):
                is_me = my_team and team.get('id') == my_team.get('id')
                name = f"[b #9fef00]{team['name']}[/]" if is_me else team['name']
                sb_dt.add_row(
                    str(i),
                    name,
                    team.get('country_code', '?'),
                    str(team.get('points', 0)),
                    f"{team.get('owned_flags', 0)}/{team.get('total_flags', '?')}",
                    key=team.get('id', i),
                )
        except Exception as e:
            self.query_one("#ctf_scoreboard_info").update(f"Scoreboard unavailable: {e}")

    def _update_action_buttons(self):
        dl_btn = self.query_one("#ctf_download_btn", Button)
        if self._selected_chall and self._selected_chall.get('filename'):
            dl_btn.disabled = False
            dl_btn.label = f"Download ({self._selected_chall['filename']})"
        else:
            dl_btn.disabled = True
            dl_btn.label = "Download"

    @on(DataTable.RowSelected, "#ctf_cat_table")
    def cat_selected(self, event):
        cat = self.app._ctf_cats.get(event.row_key.value, {})
        chall_dt = self.query_one("#ctf_chall_table", DataTable)
        chall_dt.clear()
        for c in cat.get('challenges', []):
            chall_dt.add_row(
                c['name'], c.get('difficulty', '?'),
                str(c.get('points', 0)),
                "✅" if c.get('solved') else "❌",
                key=c['id'],
            )

    @on(DataTable.RowSelected, "#ctf_chall_table")
    def chall_selected(self, event):
        chall = self.app._ctf_challenges.get(event.row_key.value)
        if not chall:
            return
        self._selected_chall = chall
        self._render_detail(chall)
        self._update_action_buttons()
        inp = self.query_one("#ctf_flag_input", Input)
        inp.placeholder = f"Flag for {chall.get('name', '?')}..."
        inp._chall_id = chall['id']

        ctf = self.app._current_ctf
        if ctf:
            tdir = _task_dir(self.app.settings.workdir, ctf, chall)
            self._current_task_dir = tdir
            ensure_task_dir(self.app, tdir, self._on_chall_dir_ready)

    def _on_chall_dir_ready(self, path):
        if path is None:
            return
        notes_path = os.path.join(path, "NOTES.md")
        editor = self.query_one("#ctf_notes_editor", NotesEditor)
        editor.set_filepath(notes_path)
        self.query_one("#ctf_notes_label", Label).update(f"Notes: {notes_path}  <ctrl+s> to save")

    def _render_detail(self, chall):
        text = f"## {chall['name']}\n\n"
        text += f"**Creator:** {chall.get('creator', '?')} | "
        text += f"**Points:** {chall.get('points', 0)} | "
        text += f"**Solves:** {chall.get('solves', 0)} | "
        text += f"**Difficulty:** {chall.get('difficulty', '?')}\n\n"

        if chall.get('solved'):
            text += "> ✅ **SOLVED**\n\n"

        text += f"{chall.get('description', '*No description*')}\n\n"
        text += "---\n\n"

        if chall.get('hasDocker'):
            text += f"**Instance type:** {chall.get('docker_instance_type', '?')}\n\n"
            if chall.get('docker_online'):
                text += f"**Status:** 🟢 RUNNING\n\n"
                text += f"**Host:** `{chall.get('hostname', '?')}`\n\n"
                text += f"**Ports:** `{chall.get('docker_ports', '?')}`\n\n"
            else:
                text += f"**Status:** 🔴 Stopped (start via web UI)\n\n"

        if chall.get('filename'):
            text += f"**Download:** `{chall['filename']}`\n\n"

        ctf = self.app._current_ctf
        if ctf:
            tdir = _task_dir(self.app.settings.workdir, ctf, chall)
            text += f"**Local dir:** `{tdir}`\n\n"

        flags_info = chall.get('flagsInfo', [])
        if flags_info:
            text += f"**Flags:** {len(flags_info)}\n"
            for fi in flags_info:
                s = "✅" if fi.get('solved') else "❌"
                text += f"- {s} {fi.get('question') or 'Flag'}\n"

        self.query_one("#ctf_chall_detail", Markdown).update(text)

    @on(Button.Pressed, "#ctf_flag_submit")
    async def submit_flag(self, event):
        inp = self.query_one("#ctf_flag_input", Input)
        chall_id = getattr(inp, '_chall_id', None)
        flag = inp.value.strip()
        if not chall_id or not flag:
            self.app.notify("Select a challenge and enter a flag", severity="warning")
            return
        self.app.post_message(EventMsg(f"CTF::SubmitFlag chall={chall_id} flag={flag}"))
        self.app.notify("Flag submission via API not supported — use web UI", severity="warning")
        inp.value = ""

    @on(Button.Pressed, "#ctf_create_dirs_btn")
    def create_dirs_pressed(self, event):
        ctf = self.app._current_ctf
        if not ctf:
            self.app.notify("No CTF loaded", severity="warning")
            return
        challenges = ctf.get('challenges', [])
        base = _ctf_base_dir(self.app.settings.workdir, ctf)
        self.app.push_screen(
            ConfirmDirsScreen(base, len(challenges)),
            self._on_confirm_dirs,
        )

    def _on_confirm_dirs(self, confirmed):
        if not confirmed:
            return
        ctf = self.app._current_ctf
        challenges = ctf.get('challenges', [])
        created = 0
        for chall in challenges:
            tdir = _task_dir(self.app.settings.workdir, ctf, chall)
            if not os.path.exists(tdir):
                os.makedirs(tdir, exist_ok=True)
                created += 1
        self.app.post_message(EventMsg(f"Created {created} task directories (total: {len(challenges)})"))
        self.app.notify(f"Created {created} directories", severity="information")

    @on(Button.Pressed, "#ctf_download_btn")
    def download_pressed(self, event):
        chall = self._selected_chall
        if not chall or not chall.get('filename'):
            self.app.notify("No downloadable file for this challenge", severity="warning")
            return
        self.app.post_message(EventMsg(f"Download started: {chall['name']}"))
        self.app.notify("Downloading...", timeout=3)
        self.run_worker(self._bg_download(chall))

    async def _bg_download(self, chall):
        try:
            ctf = self.app._current_ctf
            ctf_id = ctf['id']
            chall_id = chall['id']
            filename = chall.get('filename', 'task.zip')
            tdir = getattr(self, '_current_task_dir', None) or _task_dir(self.app.settings.workdir, ctf, chall)
            os.makedirs(tdir, exist_ok=True)
            out_file = os.path.join(tdir, filename)

            data = await self.app.CTF_API.download_bytes(
                f"/api/challenges/{chall_id}/download"
            )
            with open(out_file, "wb") as f:
                f.write(data)
            result = f"Saved {len(data)} bytes to {out_file}"

            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext in ('zip', '7z', 'tar', 'gz', 'rar'):
                pw = self.app.settings.zip_password
                cmd = self.app.settings.unpack_cmd
                execute_unpack(tdir, filename, password=pw, unpack_cmd=cmd)
                result += " | Extracted"

            self.app.post_message(EventMsg(f"Download complete: {result}"))
            self.app.notify("Download complete", severity="information")
        except Exception as e:
            self.app.post_message(ErrorMsg(e))
            self.app.notify(f"Download failed: {e}", severity="error")
