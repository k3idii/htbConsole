import os
import re
from datetime import datetime

from textual import on
from textual.widgets import DataTable, Static, Button, Sparkline, Label, Markdown, Rule, Input, TabbedContent, TabPane
from textual.containers import Container, Horizontal, Vertical
from textual.app import ComposeResult

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


def _parse_machine(machine):
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


def _format_release(release, fmt="%Y-%m-%d"):
    try:
        return datetime.strptime(release, "%Y-%m-%dT%H:%M:%S.%fZ").strftime(fmt)
    except Exception:
        return release[:10] if release else ""


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
        self.add_column(label="Name", width=20)
        self.add_column(label="OS")
        self.add_column(label="User")
        self.add_column(label="Root")
        self.add_column(label="Points")
        self.add_column(label="Release", width=12)

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


    def _append_rows(self, items):
        for machine in items:
            mid = machine["id"]
            if mid in self.machine_data:
                continue
            mdata = _parse_machine(machine)
            self.machine_data[mid] = mdata
            color = DIFFICULTY_COLORS.get(mdata['difficulty'], "#FFFFFF")
            self.add_row(
                str(mid),
                f"[{color}]{mdata['name']}",
                mdata['os'],
                "✅" if mdata['user_owned'] else "❌",
                "✅" if mdata['root_owned'] else "❌",
                str(mdata['points']),
                _format_release(mdata['release']),
                key=mid)

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
        self.add_column(label="Name", width=20)
        self.add_column(label="OS")
        self.add_column(label="User")
        self.add_column(label="Root")
        self.add_column(label="Points")
        self.add_column(label="Release", width=12)

    def on_data_table_row_selected(self, event) -> None:
        if event.control.id != self.id:
            return
        machine_details = self.app.query_one(MachineDetails)
        mid = int(event.row_key.value)
        if mid in self.machine_data:
            machine_details.set_context(event.row_key.value, self.machine_data[mid])
        else:
            machine_details.clear_context()

    def load_if_needed(self):
        if not self._loaded:
            self._loaded = True
            self.run_worker(self.update_machine_list())

    async def update_machine_list(self) -> None:
        try:
            await self.get_api().ensure_init()
            self.machine_data = {}
            self.active_ids = set()
            data = await self.get_api().async_get("/api/v4/machine/paginated?per_page=100")
            for machine in data.get("data", []):
                if not machine.get("is_competitive", False):
                    continue
                mid = machine["id"]
                self.active_ids.add(mid)
                mdata = _parse_machine(machine)
                mdata["is_competitive"] = True
                self.machine_data[mid] = mdata
            self.clear()
            sorted_machines = sorted(
                self.machine_data.values(),
                key=lambda m: m.get('release', ''), reverse=True)
            for mdata in sorted_machines:
                mid = mdata['id']
                color = DIFFICULTY_COLORS.get(mdata['difficulty'], "#FFFFFF")
                short_date = _format_release(mdata.get('release', ''))
                self.add_row(
                    str(mid),
                    f"[{color}]{mdata['name']}",
                    mdata['os'],
                    "✅" if mdata['user_owned'] else "❌",
                    "✅" if mdata['root_owned'] else "❌",
                    str(mdata['points']),
                    short_date,
                    key=mid)
            self.loading = False
            self.app.post_message(DebugMsg("SeasonalMachines", machine_count=len(self.machine_data)))
        except Exception as e:
            self.post_message(ErrorMsg(e))


class MachineDetails(Static):

    SPAWN_ENDPOINT = "/api/v4/vm/spawn"
    ARENA_START_ENDPOINT = "/api/v4/arena/start"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.selected_machine_id = None
        self.selected_machine_data = {}
        self.border_title = "Machine Info"

    def compose(self) -> ComposeResult:
        with TabbedContent(id="machine_tabbed_content"):
            with TabPane("Info", id="machine_info_tab"):
                yield Markdown("", id="machine_details")
                with Container(id="machine_control_buttons"):
                    yield Button("Start", id="spawn_machine_button", disabled=True)
            with TabPane("Feedback", id="machine_feedback_tab"):
                with Container(id="machine_feedback_container"):
                    yield Rule()
                    with Container(id="feedback_container"):
                        yield Sparkline(id="feedback_sparkline_easy")
                        yield Sparkline(id="feedback_sparkline_medium")
                        yield Sparkline(id="feedback_sparkline_hard")
                    yield Label("User Rated Difficulty")
            with TabPane("Notes", id="machine_notes_tab"):
                yield Label("Notes  <ctrl+s> to save", id="machine_notes_path")
                yield NotesEditor("", id="machine_notes_editor")

    def _is_competitive(self) -> bool:
        return self.selected_machine_data.get("is_competitive", False)

    def set_context(self, machine_id: int, machine_data: dict) -> None:
        self.selected_machine_id = machine_id
        self.selected_machine_data = dict(machine_data)
        self.app.post_message(EventMsg(f"[+] Setting context for machine: {machine_id}"))
        self.border_title = f"{self.selected_machine_data['name']}::{self.selected_machine_id}"
        self.handle_display_controls()
        self.query_one("#machine_details", Markdown).update(self.make_machine_details())
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
        self.query_one("#machine_details", Markdown).update("")

    def get_context(self) -> dict:
        return self.selected_machine_data

    def has_active_machine(self) -> bool:
        return getattr(self.app, 'active_machine_id', None) is not None

    def enable_controls(self) -> None:
        self.handle_display_controls()

    def disable_controls(self) -> None:
        self.query_one("#spawn_machine_button", Button).disabled = True

    def handle_display_controls(self) -> None:
        has_selection = self.selected_machine_id is not None
        self.query_one("#spawn_machine_button", Button).disabled = not has_selection

    def make_feedback_sparkline(self) -> None:
        feedback = self.selected_machine_data.get("feedbackForChart", {})
        feedback_data = list(feedback.values())
        self.query_one("#feedback_sparkline_easy").data = feedback_data[slice(3)]
        self.query_one("#feedback_sparkline_medium").data = feedback_data[slice(3, 6)]
        self.query_one("#feedback_sparkline_hard").data = feedback_data[slice(6, 9)]

    def make_machine_details(self) -> str:
        d = self.selected_machine_data
        if not d:
            return ""
        diff = d.get('difficulty', 'Unknown')
        user_flag = "User Flag : ✅" if d.get('user_owned') else "User Flag : ❌"
        root_flag = "Root Flag : ✅" if d.get('root_owned') else "Root Flag : ❌"
        release_date = _format_release(d.get("release", ""), "%B %d, %Y")

        lines = [
            f"**OS** : {d.get('os', '?')}  ",
            f"**Difficulty** : {diff}  ",
            f"{user_flag}  ",
            f"{root_flag}  ",
            f"**Points** : {d.get('points', 0)}  ",
            f"**Rating** : {d.get('rating', 0)}  ",
            f"**User Owns** : {d.get('user_owns_count', 0)}  ",
            f"**Root Owns** : {d.get('root_owns_count', 0)}  ",
            f"**Release** : {release_date}  ",
        ]
        self.make_feedback_sparkline()
        return "\n".join(lines)

    @on(Button.Pressed, selector="#spawn_machine_button")
    async def spawn_button_pressed(self) -> None:
        if self.has_active_machine():
            self.app.notify(
                "A machine is already active. Stop it before starting another.",
                severity="warning", timeout=5)
            return
        if self.selected_machine_id is None:
            return
        self.disable_controls()
        await self.start_machine(self.selected_machine_id)
        self.enable_controls()

    async def start_machine(self, machine_id: int) -> None:
        try:
            if self._is_competitive():
                self.app.post_message(EventMsg(f"[+] Starting arena machine"))
                data = await self.app.API.async_post(self.ARENA_START_ENDPOINT, {})
            else:
                self.app.post_message(EventMsg(f"[+] Starting machine with id: {machine_id}"))
                data = await self.app.API.async_post(self.SPAWN_ENDPOINT, {"machine_id": machine_id})
            if data:
                self.app.post_message(DebugMsg(f"[!] {data}"))
                if "message" in data:
                    self.app.post_message(EventMsg(f"[+] Machine started: {machine_id}"))
                    self.notify(data["message"])
                    await self.app.query_one(ContainerMachines).refresh_active()
        except Exception as e:
            self.app.notify(f"Start failed: {e}", severity="error", timeout=5)
            self.app.post_message(ErrorMsg(e))


class ActiveMachinePanel(Static):
    """Compact panel showing the currently active machine with stop / restart controls."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.border_title = "Active Machine"

    def compose(self) -> ComposeResult:
        yield Static("[dim]No active machine[/]", id="active_machine_details")
        with Horizontal(id="active_action_row"):
            yield Button("Stop", id="active_stop_button", variant="error", disabled=True)
            yield Button("Restart", id="active_reset_button", disabled=True)
            yield Button("Copy IP", id="active_copy_ip_button", disabled=True)
            yield Button("Refresh", id="active_refresh_button", disabled=True)
        with Horizontal(id="active_submit_flag_container"):
            yield Input(placeholder="Submit Flag", id="active_submit_flag_input", disabled=True)
            yield Button("Submit", id="active_submit_flag_button", disabled=True)

    def _info(self) -> dict:
        return getattr(self.app, 'active_machine_info', None) or {}

    def _active_id(self):
        return getattr(self.app, 'active_machine_id', None)

    def _is_competitive(self) -> bool:
        return bool(self._info().get("is_competitive", False))

    def update_active(self) -> None:
        info = self._info()
        active = self._active_id() is not None
        ip = info.get("ip", "")
        detail = self.query_one("#active_machine_details", Static)
        if active:
            segs = [f"[bold green]{info.get('name', '?')}[/]"]
            segs.append(f"[cyan]{ip}[/]" if ip else "[yellow]starting…[/]")
            if info.get("os"):
                segs.append(f"({info['os']})")
            if info.get("type"):
                segs.append(f"· {info['type']}")
            if info.get("expires_at"):
                segs.append(f"· expires {info['expires_at']}")
            detail.update("  ".join(segs))
        else:
            detail.update("[dim]No active machine[/]")
        self.query_one("#active_stop_button", Button).disabled = not active
        self.query_one("#active_reset_button", Button).disabled = not active
        self.query_one("#active_copy_ip_button", Button).disabled = not bool(ip)
        self.query_one("#active_refresh_button", Button).disabled = not active
        self.query_one("#active_submit_flag_input", Input).disabled = not active
        self.query_one("#active_submit_flag_button", Button).disabled = not active

    def _disable_all(self) -> None:
        for button in self.query(Button):
            button.disabled = True
        self.query_one("#active_submit_flag_input", Input).disabled = True

    @on(Button.Pressed, selector="#active_copy_ip_button")
    def copy_ip_pressed(self) -> None:
        ip = self._info().get("ip", "")
        if ip:
            self.app.copy_to_clipboard(ip)
            self.app.notify(f"Copied: {ip}", timeout=3)

    @on(Button.Pressed, selector="#active_refresh_button")
    async def refresh_pressed(self) -> None:
        self._disable_all()
        try:
            await self.app.query_one(ContainerMachines).refresh_active()
        except Exception as e:
            self.app.notify(f"Refresh failed: {e}", severity="error", timeout=5)
            self.app.post_message(ErrorMsg(e))
        self.update_active()

    @on(Button.Pressed, selector="#active_stop_button")
    async def stop_pressed(self) -> None:
        self._disable_all()
        await self._run_action("stop")

    @on(Button.Pressed, selector="#active_reset_button")
    async def reset_pressed(self) -> None:
        self._disable_all()
        await self._run_action("reset")

    async def _run_action(self, action: str) -> None:
        mid = self._active_id()
        if mid is None:
            self.update_active()
            return
        arena = self._is_competitive()
        paths = {
            ("stop", False): "/api/v4/vm/terminate",
            ("stop", True): "/api/v4/arena/stop",
            ("reset", False): "/api/v4/vm/reset",
            ("reset", True): "/api/v4/arena/reset",
        }
        payload = {} if arena else {"machine_id": mid}
        try:
            self.app.post_message(EventMsg(f"[-] {action.title()} active machine {mid}"))
            data = await self.app.API.async_post(paths[(action, arena)], payload)
            if data and data.get("message"):
                self.notify(data["message"])
            await self.app.query_one(ContainerMachines).refresh_active()
        except Exception as e:
            self.app.notify(f"{action.title()} failed: {e}", severity="error", timeout=5)
            self.app.post_message(ErrorMsg(e))
        self.update_active()

    @on(Input.Submitted, selector="#active_submit_flag_input")
    async def flag_submitted(self, event) -> None:
        await self._submit_flag()

    @on(Button.Pressed, selector="#active_submit_flag_button")
    async def flag_button_pressed(self, event) -> None:
        await self._submit_flag()

    async def _submit_flag(self) -> None:
        inp = self.query_one("#active_submit_flag_input", Input)
        flag = inp.value.strip()
        if not flag:
            return
        mid = self._active_id()
        if mid is None:
            return
        inp.clear()
        self._disable_all()
        self.app.notify(f"Submitting flag for machine {mid}...", timeout=3)
        try:
            if self._is_competitive():
                data = await self.app.API.async_post("/api/v4/arena/own", {"flag": flag})
            else:
                data = await self.app.API.async_post(
                    "/api/v5/machine/own", {"id": int(mid), "flag": flag})
            self.app.post_message(DebugMsg(f"Flag response: {data}"))
            msg = data.get("message", str(data)) if data else "No response"
            if data and data.get("success"):
                self.app.notify(f"✅ {msg}", severity="information", timeout=10)
                self.app.post_message(EventMsg(f"[+] Flag accepted: {msg}"))
            else:
                self.app.notify(f"❌ {msg}", severity="error", timeout=10)
                self.app.post_message(EventMsg(f"[-] Flag rejected: {msg}"))
        except Exception as e:
            self.app.notify(f"Flag submit error: {e}", severity="error", timeout=10)
            self.app.post_message(ErrorMsg(e))
        self.update_active()



class ContainerMachines(Container):

    BINDINGS = [
        ("escape", "focus_list", "Focus list"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._activated = False
        self._polling = False

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
        info = self.app.active_machine_info
        if info and not info.get("ip") and not self._polling:
            self.app.notify("Machine starting — waiting for IP...", timeout=5)
            self.run_worker(self._poll_for_ip())

    async def _poll_for_ip(self):
        import asyncio
        self._polling = True
        try:
            for _ in range(36):
                await asyncio.sleep(5)
                try:
                    data = await self.app.API.async_get("/api/v4/machine/active", cache_this=0)
                    info = data.get("info")
                except Exception:
                    return
                if not info:
                    return
                self._apply_active(info)
                if info.get("ip"):
                    self.app.notify(f"Machine ready: {info['ip']}", timeout=5)
                    return
            self.app.notify(
                "Machine still starting after a while — press Refresh on the active panel to update.",
                severity="warning", timeout=8)
        finally:
            self._polling = False

    def _apply_active(self, info):
        if info:
            aid = info.get("id")
            info = dict(info)
            info["is_competitive"] = self._active_is_competitive(aid)
            self.app.active_machine_id = aid
            self.app.active_machine_info = info
        else:
            self.app.active_machine_id = None
            self.app.active_machine_info = None
        self.query_one(ActiveMachinePanel).update_active()

    def _active_is_competitive(self, aid) -> bool:
        if aid is None:
            return False
        try:
            return aid in self.query_one(SeasonalMachines).active_ids
        except Exception:
            return False

    @on(Button.Pressed, selector="#machines_reload_button")
    def reload_all(self, event) -> None:
        self.query_one(CurrentMachines).reload_machines()
        self.query_one(SeasonalMachines)._loaded = False
        self.query_one(SeasonalMachines).load_if_needed()
        self.query_one(RetiredMachines).reload_machines()
        self.app.notify("Reloading machines...", timeout=3)

    def compose(self) -> ComposeResult:
        with Container(id="machines_container") as machines_container:
            machines_container.border_title = "Machines"
            yield Button("Reload", id="machines_reload_button")
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
            yield ActiveMachinePanel(id="active_machine_panel")
            yield MachineDetails(id="machine_control")
