import os
import re
from datetime import datetime
from textual import on
from textual.app import ComposeResult
from textual.widgets import Static, Button, Sparkline, Label, Rule, Input, TabbedContent, TabPane, TextArea
from textual.containers import Container
from textual.reactive import Reactive

from rich.table import Table

from .messages import DebugMsg, ErrorMsg, EventMsg


_clean_re = re.compile('[^0-9a-zA-Z_]+')

def _machine_dir(name, workdir="./work"):
    clean = _clean_re.sub('', name.lower())
    return os.path.join(workdir, 'machines', clean)


class MachineNotesEditor(TextArea):
    language = "markdown"
    FILE: str = None

    BINDINGS = [("ctrl+s", "save_file")]

    def action_save_file(self):
        if self.FILE is None:
            return
        open(self.FILE, "w").write(self.text)
        self.app.post_message(EventMsg(f"SAVED {self.FILE}"))

    def set_filepath(self, fp):
        if self.FILE is not None:
            self.action_save_file()
        self.FILE = fp
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        if not os.path.exists(fp):
            open(fp, "w").write("")
        with open(fp, "r") as f:
            self.text = f.read()
        self.app.post_message(EventMsg(f"Loaded notes from {self.FILE}"))

    def on_unmount(self):
        self.action_save_file()



class MachineDetails(Static):

    endpoint = "/api/v4/search/fetch?query=" # + keyword + "&tags=" + filter
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

    machine_difficulty_map = {
            "Easy": "#90cd3f",
            "Medium": "#ffb83e",
            "Hard": "#fe0000",
            "Insane": "#ffccff"
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
                yield MachineNotesEditor("", id="machine_notes_editor")

    async def on_mount(self):
        self.run_worker(self._fetch_active_machine())

    async def _fetch_active_machine(self):
        try:
            await self.app.API.ensure_init()
            data = await self.app.API.async_get("/api/v4/machine/active", cache_this=0)
            info = data.get("info")
            if info:
                self.active_machine_data = info
        except Exception:
            pass

    def _is_competitive(self) -> bool:
        return self.selected_machine_data.get("is_competitive", False)

    def set_context(self, machine_id: int, machine_data: dict) -> None:
        self.selected_machine_id = machine_id
        self.selected_machine_data = machine_data
        self.border_title = f"{self.selected_machine_data['name']}::{self.selected_machine_id}"
        self.handle_display_controls()
        self.query_one("#machine_details").update(self.make_machine_details())
        self._load_notes()

    def _load_notes(self):
        name = self.selected_machine_data.get("name", "unknown")
        workdir = getattr(self.app, 'WORKDIR', './work')
        mdir = _machine_dir(name, workdir)
        note_path = os.path.join(mdir, "NOTES.md")
        editor = self.query_one("#machine_notes_editor", MachineNotesEditor)
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
        return bool(self.active_machine_data)

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

        table.add_row(
            self.selected_machine_data["os"],
            f"[{self.machine_difficulty_map[self.selected_machine_data['difficulty']]}]{self.selected_machine_data['difficulty']}"
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
                    await self._fetch_active_machine()
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
                    self.active_machine_data = {}
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
