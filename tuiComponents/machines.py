import os
import re
from datetime import datetime

from textual import on
from textual.widgets import DataTable, Static, Button, Sparkline, Label, Rule, Input, TabbedContent, TabPane
from textual.containers import Container, Vertical
from textual.app import ComposeResult
from textual.reactive import Reactive

from rich.table import Table

from httpApi import HTBApiSession
from .messages import DebugMsg, ErrorMsg, EventMsg
from .notes_editor import NotesEditor
from .confirm_dir import ensure_task_dir


_clean_re = re.compile('[^0-9a-zA-Z_]+')

def _machine_dir(name, workdir="./work"):
    clean = _clean_re.sub('', name.lower())
    return os.path.join(workdir, 'machines', clean)


DIFFICULTY_COLORS = {
    "Easy": "#90cd3f",
    "Medium": "#ffb83e",
    "Hard": "#fe0000",
    "Insane": "#ffccff",
}


class _PaginatedMachineTable(DataTable):
    """Base class for paginated machine tables with infinite scroll."""

    PER_PAGE = 50
    _MORE_KEY = "__more__"
    _ENDPOINT = "/api/v4/machine/paginated"

    def get_api(self) -> HTBApiSession:
        return self.app.get_api()

    def _init_table(self, table_id):
        self.loading = True
        self.id = table_id
        self.machine_data = {}
        self.show_header = True
        self.cursor_type = "row"
        self.current_page = 1
        self.total_pages = 1
        self._loading_more = False
        self._loaded = False

        self.add_column(label="ID")
        self._name_col = self.add_column(label="Name", width=20)
        self.add_column(label="OS")
        self.add_column(label="User")
        self.add_column(label="Root")
        self.add_column(label="Points")
        self.add_column(label="Rating")

    def on_data_table_row_selected(self, event) -> None:
        if event.control.id != self.id or event.row_key.value == self._MORE_KEY:
            return
        machine_details = self.app.query_one(MachineDetails)
        machine_details.set_context(event.row_key.value, event.control.machine_data[int(event.row_key.value)])

    def on_data_table_row_highlighted(self, event) -> None:
        if event.row_key and event.row_key.value == self._MORE_KEY and not self._loading_more:
            self._load_more()

    def _remove_sentinel(self):
        try:
            self.remove_row(self._MORE_KEY)
        except Exception:
            pass

    def _add_sentinel(self):
        self.add_row("", ".... more ....", "", "", "", "", "", key=self._MORE_KEY)

    def _parse_machine(self, machine):
        return {
            "name": machine["name"],
            "id": machine["id"],
            "os": machine["os"],
            "difficulty": machine.get("difficultyText", "Unknown"),
            "user_owned": machine.get("authUserInUserOwns", False),
            "root_owned": machine.get("authUserInRootOwns", False),
            "points": machine.get("points", 0),
            "rating": machine.get("star", 0),
            "release": machine.get("release", ""),
            "active": machine.get("active"),
            "labels": machine.get("labels", []),
            "feedbackForChart": machine.get("feedbackForChart", {}),
            "is_competitive": machine.get("is_competitive", False),
            "user_owns_count": machine.get("user_owns_count", 0),
            "root_owns_count": machine.get("root_owns_count", 0),
        }

    def _format_name(self, mdata, active_id=None):
        color = DIFFICULTY_COLORS.get(mdata['difficulty'], "#FFFFFF")
        prefix = "▶ " if mdata['id'] == active_id else ""
        return f"{prefix}[{color}]{mdata['name']}"

    def _append_rows(self, items):
        active_id = getattr(self.app, 'active_machine_id', None)
        for machine in items:
            mid = machine["id"]
            if mid in self.machine_data:
                continue
            mdata = self._parse_machine(machine)
            self.machine_data[mid] = mdata
            self.add_row(
                str(mid),
                self._format_name(mdata, active_id),
                mdata['os'],
                "✅" if mdata['user_owned'] else "❌",
                "✅" if mdata['root_owned'] else "❌",
                str(mdata['points']),
                str(mdata['rating']),
                key=mid)

    def mark_active(self, active_id):
        for mid, mdata in self.machine_data.items():
            try:
                self.update_cell(mid, self._name_col, self._format_name(mdata, active_id))
            except Exception:
                pass

    async def _do_load(self):
        try:
            await self.get_api().ensure_init()
            data = await self.get_api().async_get(
                f"{self._ENDPOINT}?per_page={self.PER_PAGE}&page={self.current_page}",
                cache_this=0)
            meta = data.get("meta", {})
            self.current_page = meta.get("current_page", 1)
            self.total_pages = meta.get("last_page", 1)

            self._remove_sentinel()
            self._append_rows(data.get("data", []))
            if self.current_page < self.total_pages:
                self._add_sentinel()
            self.loading = False
            self._loading_more = False
            self.app.post_message(DebugMsg(
                f"{self.id}::loaded", count=len(self.machine_data),
                page=f"{self.current_page}/{self.total_pages}"))
        except Exception as e:
            self._loading_more = False
            self.post_message(ErrorMsg(e))

    def _load_more(self):
        if self.current_page >= self.total_pages or self._loading_more:
            return
        self._loading_more = True
        self.current_page += 1
        self.run_worker(self._do_load())

    def reload_machines(self):
        self.current_page = 1
        self.machine_data = {}
        self.clear()
        self.loading = True
        self._loaded = True
        self.run_worker(self._do_load())

    def load_if_needed(self):
        if not self._loaded:
            self._loaded = True
            self.run_worker(self._do_load())


class CurrentMachines(_PaginatedMachineTable):
    _ENDPOINT = "/api/v4/machine/paginated"

    def __init__(self) -> None:
        super().__init__()
        self._init_table("current_machines")


class RetiredMachines(_PaginatedMachineTable):
    _ENDPOINT = "/api/v4/machine/list/retired/paginated"

    def __init__(self) -> None:
        super().__init__()
        self._init_table("retired_machines")


class SeasonalMachines(DataTable):
    """DataTable widget that shows the seasonal/competitive machines."""

    def get_api(self) -> HTBApiSession:
        return self.app.get_api()

    def __init__(self) -> None:
        super().__init__()
        self.loading = True
        self.id = "seasonal_machines"
        self.machine_data = {}
        self.active_ids = set()
        self.show_header = True
        self.cursor_type = "row"
        self._loaded = False

        self.add_column(label="ID")
        self._name_col = self.add_column(label="Name", width=20)
        self.add_column(label="OS")
        self.add_column(label="User")
        self.add_column(label="Root")
        self.add_column(label="Points")
        self.add_column(label="Rating")

    def on_data_table_row_selected(self, event) -> None:
        if event.control.id != self.id:
            return
        machine_details = self.app.query_one(MachineDetails)
        mid = int(event.row_key.value)
        if mid in self.machine_data:
            machine_details.set_context(event.row_key.value, self.machine_data[mid])
        else:
            machine_details.clear_context()

    def _format_name(self, mdata, active_id=None):
        color = DIFFICULTY_COLORS.get(mdata['difficulty'], "#FFFFFF")
        prefix = "▶ " if mdata['id'] == active_id else ""
        return f"{prefix}[{color}]{mdata['name']}"

    def mark_active(self, active_id):
        for mid, mdata in self.machine_data.items():
            try:
                self.update_cell(mid, self._name_col, self._format_name(mdata, active_id))
            except Exception:
                pass

    def load_if_needed(self):
        if not self._loaded:
            self._loaded = True
            self.run_worker(self.update_machine_list())

    async def update_machine_list(self) -> None:
        try:
            await self.get_api().ensure_init()
            self.machine_data = {}
            self.active_ids = set()
            active_id = getattr(self.app, 'active_machine_id', None)
            data = await self.get_api().async_get("/api/v4/machine/paginated?per_page=100")
            for machine in data.get("data", []):
                if not machine.get("is_competitive", False):
                    continue
                mid = machine["id"]
                self.active_ids.add(mid)
                self.machine_data[mid] = {
                    "name": machine["name"],
                    "id": mid,
                    "os": machine["os"],
                    "difficulty": machine.get("difficultyText", "Unknown"),
                    "user_owned": machine.get("authUserInUserOwns", False),
                    "root_owned": machine.get("authUserInRootOwns", False),
                    "points": machine.get("points", 0),
                    "rating": machine.get("star", 0),
                    "release": machine.get("release", ""),
                    "active": machine.get("active"),
                    "labels": machine.get("labels", []),
                    "feedbackForChart": machine.get("feedbackForChart", {}),
                    "is_competitive": True,
                    "user_owns_count": machine.get("user_owns_count", 0),
                    "root_owns_count": machine.get("root_owns_count", 0),
                }
            self.clear()
            for mid, mdata in self.machine_data.items():
                self.add_row(
                    str(mid),
                    self._format_name(mdata, active_id),
                    mdata['os'],
                    "✅" if mdata['user_owned'] else "❌",
                    "✅" if mdata['root_owned'] else "❌",
                    str(mdata['points']),
                    str(mdata['rating']),
                    key=mid)
            self.loading = False
            self.app.post_message(DebugMsg("SeasonalMachines", machine_count=len(self.machine_data)))
        except Exception as e:
            self.post_message(ErrorMsg(e))


class MachineDetails(Static):

    endpoint = "/api/v4/search/fetch?query="
    endpoints = {
        "POST": {
            "spawn_machine": "/api/v4/vm/spawn",
            "terminate_machine": "/api/v4/vm/terminate",
            "reset_machine": "/api/v4/vm/reset",
            "start_arena_machine": "/api/v4/arena/start",
            "stop_arena_machine": "/api/v4/arena/stop",
            "reset_arena_machine": "/api/v4/arena/reset",
            "submit_flag": "/api/v4/machine/own",
            "submit_arena_flag": "/api/v4/arena/own",
        }
    }

    active_machine_data = Reactive({})

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.selected_machine_id: int = 0
        self.selected_machine_data = {}
        self.border_title = "Machine Info"

    def compose(self) -> ComposeResult:
        with TabbedContent(id="machine_tabbed_content"):
            with TabPane("Info", id="machine_info_tab"):
                yield Static(id="machine_details")
                with Container(id="machine_feedback_container"):
                    yield Rule()
                    with Container(id="feedback_container"):
                        yield Sparkline(id="feedback_sparkline_easy")
                        yield Sparkline(id="feedback_sparkline_medium")
                        yield Sparkline(id="feedback_sparkline_hard")
                    yield Label("User Rated Difficulty")
                with Container(id="machine_control_buttons"):
                    with Container(id="submit_flag_container"):
                        yield Input(placeholder="Submit Flag", id="submit_flag_input")
                        yield Button("Submit", id="submit_flag_button")
                    yield Button("Spawn Machine", id="spawn_machine_button")
                    yield Button("Stop Machine", id="stop_machine_button", variant="error")
                    yield Button("Reset Machine", id="reset_machine_button", variant="default")
            with TabPane("Notes", id="machine_notes_tab"):
                yield Label("Notes  <ctrl+s> to save", id="machine_notes_path")
                yield NotesEditor("", id="machine_notes_editor")

    def _is_competitive(self) -> bool:
        return self.selected_machine_data.get("is_competitive", False)

    def set_context(self, machine_id: int, machine_data: dict) -> None:
        self.selected_machine_id = machine_id
        self.selected_machine_data = machine_data
        self.app.post_message(EventMsg(f"[+] Setting context for machine: {machine_id}"))
        self.border_title = f"{self.selected_machine_data['name']}::{self.selected_machine_id}"
        self.handle_display_controls()
        self.query_one("#machine_details").update(self.make_machine_details())
        name = self.selected_machine_data.get("name", "unknown")
        workdir = self.app.settings.workdir
        self._task_dir = _machine_dir(name, workdir)
        ensure_task_dir(self.app, self._task_dir, self._on_dir_ready)

    def _on_dir_ready(self, path):
        if path is None:
            return
        note_path = os.path.join(path, "NOTES.md")
        editor = self.query_one("#machine_notes_editor", NotesEditor)
        editor.set_filepath(note_path)
        self.query_one("#machine_notes_path").update(f"Notes: {note_path}  <ctrl+s> to save")

    def clear_context(self) -> None:
        self.app.post_message(EventMsg(f"[-] Clearing machine context"))
        self.selected_machine_id = None
        self.selected_machine_data = {}
        self.border_title = "Machine Info"
        self.handle_display_controls()
        self.query_one("#machine_details").update("")

    def get_context(self) -> dict:
        return self.selected_machine_data

    def has_active_machine(self) -> bool:
        return getattr(self.app, 'active_machine_id', None) is not None

    def watch_active_machine_data(self, old_value, new_value) -> None:
        self.app.post_message(EventMsg(f"[+] Active machine data changed"))
        if new_value:
            mid = new_value.get("id")
            if mid:
                self.set_context(mid, new_value)
        else:
            self.clear_context()

    def enable_controls(self) -> None:
        for button in self.query(Button):
            button.disabled = False
        self.query_one("#submit_flag_input").disabled = False

    def disable_controls(self) -> None:
        for button in self.query(Button):
            button.disabled = True
        self.query_one("#submit_flag_input").disabled = True

    def handle_display_controls(self) -> None:
        self.enable_controls()
        if self.has_active_machine():
            self.add_class("active")
            self.remove_class("inactive")
        elif self.selected_machine_id is not None:
            self.remove_class("active")
            self.add_class("inactive")
        else:
            self.remove_class("active")
            self.remove_class("inactive")

    def make_feedback_sparkline(self) -> None:
        feedback = self.selected_machine_data.get("feedbackForChart", {})
        feedback_data = list(feedback.values())
        self.query_one("#feedback_sparkline_easy").data = feedback_data[slice(3)]
        self.query_one("#feedback_sparkline_medium").data = feedback_data[slice(3, 6)]
        self.query_one("#feedback_sparkline_hard").data = feedback_data[slice(7, 10)]

    def make_machine_details(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(justify="justify")
        table.add_column(justify="justify")

        diff = self.selected_machine_data['difficulty']
        color = DIFFICULTY_COLORS.get(diff, "#FFFFFF")
        table.add_row(
            self.selected_machine_data["os"],
            f"[{color}]{diff}"
        )
        table.add_row(
            "User Flag ✅" if self.selected_machine_data['user_owned'] else "User Flag ❌",
            "Root Flag ✅" if self.selected_machine_data['root_owned'] else "Root Flag ❌"
        )
        table.add_row(
            f"{self.selected_machine_data['points']} points",
            f"{self.selected_machine_data['rating']} stars"
        )
        table.add_row("User Owns", str(self.selected_machine_data["user_owns_count"]))
        table.add_row("Root Owns", str(self.selected_machine_data["root_owns_count"]))

        release_date = datetime.strptime(self.selected_machine_data["release"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%B %d, %Y")
        table.add_row("Release", release_date)

        self.make_feedback_sparkline()
        return table

    @on(Button.Pressed, selector="#spawn_machine_button")
    async def spawn_button_pressed(self) -> None:
        self.disable_controls()
        await self.start_machine(self.selected_machine_id)
        self.enable_controls()

    async def start_machine(self, machine_id: int) -> None:
        try:
            if self._is_competitive():
                self.app.post_message(EventMsg(f"[+] Starting arena machine"))
                data = await self.start_arena_machine()
            else:
                self.app.post_message(EventMsg(f"[+] Starting machine with id: {machine_id}"))
                data = await self.spawn_machine(machine_id)
            if data:
                self.app.post_message(DebugMsg(f"[!] {data}"))
                if "message" in data:
                    self.app.post_message(EventMsg(f"[+] Machine started: {machine_id}"))
                    self.notify(data["message"])
                    await self.app.query_one(ContainerMachines).refresh_active()
        except Exception as e:
            self.app.post_message(ErrorMsg(e))

    @on(Button.Pressed, selector="#stop_machine_button")
    async def stop_button_pressed(self) -> None:
        self.disable_controls()
        await self.stop_machine()
        self.enable_controls()

    async def stop_machine(self) -> None:
        try:
            if self._is_competitive():
                self.app.post_message(EventMsg(f"[-] Stopping arena machine"))
                data = await self.stop_arena_machine()
            else:
                self.app.post_message(EventMsg(f"[-] Stopping machine with id: {self.selected_machine_id}"))
                data = await self.terminate_machine(self.selected_machine_id)
            if data:
                self.app.post_message(DebugMsg(f"[!] {data}"))
                if "message" in data:
                    self.app.post_message(EventMsg(f"[+] Machine stopped"))
                    self.notify(data["message"])
                    await self.app.query_one(ContainerMachines).refresh_active()
        except Exception as e:
            self.app.post_message(ErrorMsg(e))

    @on(Button.Pressed, selector="#reset_machine_button")
    async def reset_button_pressed(self) -> None:
        self.disable_controls()
        await self.reset_machine()
        self.enable_controls()

    async def reset_machine(self) -> None:
        try:
            if self._is_competitive():
                self.app.post_message(EventMsg(f"[-] Resetting arena machine"))
                data = await self.reset_arena_machine()
            else:
                self.app.post_message(EventMsg(f"[-] Resetting machine with id: {self.selected_machine_id}"))
                data = await self.respawn_machine(self.selected_machine_id)
            if data:
                self.app.post_message(DebugMsg(f"[!] {data}"))
                if "message" in data:
                    self.app.post_message(DebugMsg(f"[!] {data['message']}"))
                    self.notify(data["message"])
        except Exception as e:
            self.app.post_message(ErrorMsg(e))

    @on(Input.Submitted, selector="#submit_flag_input")
    async def handle_input(self, event: Input.Submitted) -> None:
        self.disable_controls()
        event.control.clear()
        await self.submit_flag(event.value, self.selected_machine_id)
        self.enable_controls()

    async def submit_flag(self, flag: str, machine_id: int = None) -> None:
        try:
            if self._is_competitive():
                self.app.post_message(EventMsg(f"[+] Submitting flag for arena machine"))
                data = await self.send_arena_flag(flag)
            else:
                self.app.post_message(EventMsg(f"[+] Submitting flag for machine with id: {machine_id}"))
                data = await self.send_flag(flag, machine_id)
            if data:
                self.app.post_message(DebugMsg(f"[!] {data}"))
                if "message" in data:
                    self.app.post_message(EventMsg(f"[!] {data['message']}"))
                    self.notify(data["message"])
        except Exception as e:
            self.app.post_message(ErrorMsg(e))

    async def spawn_machine(self, machine_id: int):
        return await self.app.API.async_post(
            self.endpoints["POST"]["spawn_machine"],
            {"machine_id": machine_id})

    async def terminate_machine(self, machine_id: int):
        return await self.app.API.async_post(
            self.endpoints["POST"]["terminate_machine"],
            {"machine_id": machine_id})

    async def respawn_machine(self, machine_id: int):
        return await self.app.API.async_post(
            self.endpoints["POST"]["reset_machine"],
            {"machine_id": machine_id})

    async def start_arena_machine(self):
        return await self.app.API.async_post(
            self.endpoints["POST"]["start_arena_machine"], {})

    async def stop_arena_machine(self):
        return await self.app.API.async_post(
            self.endpoints["POST"]["stop_arena_machine"], {})

    async def reset_arena_machine(self):
        return await self.app.API.async_post(
            self.endpoints["POST"]["reset_arena_machine"], {})

    async def send_flag(self, flag: str, machine_id: int):
        return await self.app.API.async_post(
            self.endpoints["POST"]["submit_flag"],
            {"id": machine_id, "flag": flag})

    async def send_arena_flag(self, flag: str):
        return await self.app.API.async_post(
            self.endpoints["POST"]["submit_arena_flag"],
            {"flag": flag})


class ContainerMachines(Container):

    BINDINGS = [
        ("escape", "focus_list", "Focus list"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._activated = False

    def action_focus_list(self):
        try:
            self.query_one("#current_machines").focus()
        except Exception:
            pass

    def activate(self):
        if self._activated:
            return
        self._activated = True
        self.query_one(CurrentMachines).load_if_needed()
        self.query_one(SeasonalMachines).load_if_needed()
        self.query_one(RetiredMachines).load_if_needed()
        self.run_worker(self._fetch_active_machine())

    async def _fetch_active_machine(self):
        try:
            await self.app.API.ensure_init()
            data = await self.app.API.async_get("/api/v4/machine/active", cache_this=0)
            info = data.get("info")
            self._apply_active(info)
        except Exception:
            pass

    async def refresh_active(self):
        await self._fetch_active_machine()

    def _apply_active(self, info):
        details = self.query_one(MachineDetails)
        if info:
            mid = info.get("id")
            self.app.active_machine_id = mid
            self.app.active_machine_info = info
            self._update_status(info)
            self._mark_all_tables(mid)
            details.active_machine_data = info
        else:
            self.app.active_machine_id = None
            self.app.active_machine_info = None
            self._update_status(None)
            self._mark_all_tables(None)
            details.active_machine_data = {}

    def _update_status(self, machine_data):
        label = self.query_one("#machine_active_status", Static)
        if machine_data:
            name = machine_data.get("name", "?")
            ip = machine_data.get("ip", "")
            os_name = machine_data.get("os", "")
            parts = [f"[bold green]{name}[/]"]
            if ip:
                parts.append(f"@ {ip}")
            if os_name:
                parts.append(f"({os_name})")
            label.update(f"Active: {' '.join(parts)}")
        else:
            label.update("Active: [dim]NONE[/]")

    def _mark_all_tables(self, active_id):
        for table_cls in [CurrentMachines, SeasonalMachines, RetiredMachines]:
            try:
                table = self.query_one(table_cls)
                table.mark_active(active_id)
                table.refresh()
            except Exception:
                pass

    def compose(self) -> ComposeResult:
        with Container(id="machines_container") as machines_container:
            machines_container.border_title = "Machines"
            with TabbedContent(id="machines_tabbed_content"):
                with TabPane("Current Machines", id="current_machines_tab"):
                    with Container(id="current_machines_container"):
                        yield CurrentMachines()
                with TabPane("Seasonal Machines", id="seasonal_machines_tab"):
                    with Container(id="seasonal_machines_container"):
                        yield SeasonalMachines()
                with TabPane("Retired Machines", id="retired_machines_tab"):
                    with Container(id="retired_machines_container"):
                        yield RetiredMachines()
        with Vertical(id="machine_right_pane"):
            yield Static("Active: [dim]NONE[/]", id="machine_active_status")
            yield MachineDetails(id="machine_control")
