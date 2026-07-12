import os

from textual import on
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import (
    Label, TabbedContent, TabPane,
    DataTable, Static, Button,
)
from textual.containers import Container, Horizontal

from rich.table import Table

from .messages import ErrorMsg, EventMsg


class JoinCTFScreen(ModalScreen):

    CSS = """
    JoinCTFScreen { align: center middle; }
    #join_dialog { width: 60%; height: auto; padding: 2; background: #1a2332; border: panel #3d5276; }
    #join_dialog Label { width: 100%; margin-bottom: 1; }
    #join_buttons { layout: horizontal; width: 100%; }
    #join_buttons Button { width: 1fr; }
    """

    def __init__(self, ctf_data):
        super().__init__()
        self.ctf_data = ctf_data

    def compose(self) -> ComposeResult:
        ctf = self.ctf_data
        has_joined = ctf.get('hasJoined')
        with Container(id="join_dialog"):
            yield Label(f"[b]{ctf['name']}[/b]")
            yield Label(f"Status: {ctf['status']} | Team size: {ctf.get('team_size', '?')} | {ctf.get('membersJoined', '?')}")
            joined_team = ctf.get('joinedTeam')
            if joined_team:
                yield Label(f"Your team: {joined_team}")
            else:
                yield Label("[bold red]You have not joined this CTF.[/] Join via web UI first:")
                slug = ctf.get('slug', '')
                yield Label(f"https://ctf.hackthebox.com/event/{slug}")
            yield Label(f"{ctf.get('starts_at', '?')[:16]} → {ctf.get('ends_at', '?')[:16]}")
            yield Label("")
            if has_joined:
                yield Label("Enter this CTF?")
                with Horizontal(id="join_buttons"):
                    yield Button("Yes", id="join_yes", variant="success")
                    yield Button("No", id="join_no")
            else:
                with Horizontal(id="join_buttons"):
                    yield Button("Close", id="join_no")

    def on_button_pressed(self, event):
        self.dismiss(self.ctf_data if event.button.id == "join_yes" else None)


class CTFTable(DataTable):

    def __init__(self, table_id):
        super().__init__()
        self.id = table_id
        self.show_header = True
        self.cursor_type = "row"
        self.add_column(label="ID")
        self.add_column(label="Name", width=30)
        self.add_column(label="Status")
        self.add_column(label="Team")
        self.add_column(label="Start")
        self.add_column(label="Ends")

    def populate(self, ctfs):
        self.clear()
        for ctf in ctfs:
            self._add_ctf_row(ctf)

    def _add_ctf_row(self, ctf):
        team = ctf.get('joinedTeam') or (ctf.get('participating_team') or {}).get('name') or "-"
        self.add_row(
            str(ctf['id']),
            ctf['name'],
            ctf.get('status', '?'),
            team,
            ctf.get('starts_at', '?')[:10],
            ctf.get('ends_at', '?')[:10],
            key=ctf['id'],
        )

    def on_data_table_row_selected(self, event):
        if event.control.id != self.id:
            return
        if event.row_key.value == "__more__":
            return
        ctf = self.app._ctf_cache.get(event.row_key.value)
        if ctf:
            self.app.push_screen(JoinCTFScreen(ctf), self.app._on_ctf_join)


class OngoingCTFTable(CTFTable):

    def __init__(self):
        super().__init__("ctf_ongoing_table")
        self.add_column(label="Play")
        self.add_column(label="Join")
        self.add_column(label="In")

    def _add_ctf_row(self, ctf):
        can_play = "✅" if ctf.get('canPlay') else "❌"
        can_join = "✅" if ctf.get('canJoin') else "❌"
        has_joined = "✅" if ctf.get('hasJoined') else "❌"
        joined_team = ctf.get('joinedTeam') or "-"
        self.add_row(
            str(ctf['id']),
            ctf['name'],
            ctf.get('status', '?'),
            joined_team,
            ctf.get('starts_at', '?')[:10],
            ctf.get('ends_at', '?')[:10],
            can_play,
            can_join,
            has_joined,
            key=ctf['id'],
        )


class PastCTFTable(CTFTable):

    _MORE_KEY = "__more__"

    def on_data_table_row_selected(self, event):
        pass

    def __init__(self):
        super().__init__("ctf_past_table")
        self._current_page = 0
        self._total_pages = 1
        self._loading_more = False
        self._loaded = False
        self._seen_ids = set()

    def load_initial(self):
        if self._loaded:
            return
        self._loaded = True
        self._current_page = 1
        self.run_worker(self._do_load())

    def on_data_table_row_highlighted(self, event):
        if event.row_key and event.row_key.value == self._MORE_KEY and not self._loading_more:
            self._load_more()

    def _remove_sentinel(self):
        try:
            self.remove_row(self._MORE_KEY)
        except Exception:
            pass

    def _add_sentinel(self):
        self.add_row("", ".... more ....", "", "", "", "", key=self._MORE_KEY)

    def _load_more(self):
        if self._current_page >= self._total_pages or self._loading_more:
            return
        self._loading_more = True
        self._current_page += 1
        self.run_worker(self._do_load())

    async def _do_load(self):
        try:
            data = await self.app.CTF_API.api_ctf_past(params={"page": self._current_page, "search": ""})
            ctfs = data.get("data", data) if isinstance(data, dict) else data
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            if meta:
                self._current_page = meta.get("current_page", self._current_page)
                self._total_pages = meta.get("last_page", self._total_pages)

            self._remove_sentinel()
            for ctf in (ctfs if isinstance(ctfs, list) else []):
                if ctf['id'] in self._seen_ids:
                    continue
                self._seen_ids.add(ctf['id'])
                self.app._ctf_cache[ctf['id']] = ctf
                self._add_ctf_row(ctf)

            if self._current_page < self._total_pages:
                self._add_sentinel()

            self._loading_more = False
            self.app.post_message(EventMsg(
                f"PastCTFs::{len(self._seen_ids)} loaded (page {self._current_page}/{self._total_pages})"))
        except Exception as e:
            self._loading_more = False
            self.app.post_message(ErrorMsg(e))


class CTFListView(Container):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._past_loaded = False

    def compose(self) -> ComposeResult:
        yield Static(id="ctf_player_info")
        with TabbedContent(id="ctf_list_tabs"):
            with TabPane("Ongoing", id="tab_ongoing"):
                yield OngoingCTFTable()
            with TabPane("Upcoming", id="tab_upcoming"):
                yield CTFTable("ctf_upcoming_table")
            with TabPane("Past", id="tab_past"):
                yield PastCTFTable()

    async def on_mount(self):
        self.run_worker(self._load())

    @on(TabbedContent.TabActivated, "#ctf_list_tabs")
    def _on_tab_activated(self, event):
        if event.pane.id == "tab_past" and not self._past_loaded:
            self._past_loaded = True
            self.query_one(PastCTFTable).load_initial()

    async def _load(self):
        try:
            ctfs = await self.app.CTF_API.api_ctf_list()
            self.app._ctf_cache = {c['id']: c for c in ctfs}

            ongoing = [c for c in ctfs if c.get('status') == 'Ongoing']
            upcoming = [c for c in ctfs if c.get('status') == 'Upcoming']

            self.query_one(OngoingCTFTable).populate(ongoing)
            self.query_one("#ctf_upcoming_table", CTFTable).populate(upcoming)

            info = Table.grid(expand=True)
            info.add_column(ratio=1)
            info.add_column(ratio=1)
            info.add_row(f"Total: {len(ctfs)}", f"Ongoing: {len(ongoing)}")
            info.add_row(f"Upcoming: {len(upcoming)}", "")
            self.query_one("#ctf_player_info").update(info)
        except Exception as e:
            self.app.post_message(ErrorMsg(e))
