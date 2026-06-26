import os
import re

from textual.widgets import DataTable, Button, Label, Input, Markdown, Static, TabbedContent, TabPane, Select
from textual.screen import ModalScreen
from textual import on
from textual.containers import Container, VerticalScroll, Horizontal
from textual.app import ComposeResult
from rich.table import Table

from .messages import DebugMsg, ErrorMsg, EventMsg
from .downloader import async_download_and_extract
from .confirm_dir import ensure_task_dir

sherlock_difficulty_map = {
    "Very Easy": "#90ff3f",
    "Easy": "#90cd3f",
    "Medium": "#ffb83e",
    "Hard": "#fe0000",
    "Insane": "#ffccff",
}

_clean_re = re.compile('[^0-9a-zA-Z_]+')

def _is_task_completed(task):
    return task.get("is_complete", False) or task.get("completed", False)


def _sherlock_dir(name, workdir="./work"):
    clean = _clean_re.sub('', name.lower())
    return os.path.join(workdir, 'sherlocks', clean)


SHERLOCK_CATEGORIES = ["DFIR", "SOC", "Malware Analysis", "Threat Intelligence", "Cloud"]
SHERLOCK_DIFFICULTIES = ["Easy", "Medium", "Hard", "Insane"]


class SherlockFilter:
    def __init__(self):
        self.difficulty = []
        self.category = ""
        self.state = ""

    def serialize(self):
        params = []
        for d in self.difficulty:
            params.append(("difficulty[]", d.lower()))
        if self.category:
            params.append(("category_name", self.category))
        if self.state:
            params.append(("state", self.state))
        return params

    def __repr__(self):
        parts = []
        if self.difficulty:
            parts.append(",".join(self.difficulty))
        if self.category:
            parts.append(self.category)
        if self.state:
            parts.append(self.state)
        return " | ".join(parts) if parts else "<no filter>"


class SherlockFilterScreen(ModalScreen):

    CSS = """
    SherlockFilterScreen {
        align: center middle;
    }
    #sherlock_filter_popup {
        width: 50%;
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="sherlock_filter_popup"):
            yield Label("Filter Sherlocks")
            yield Select(
                ((c, c) for c in SHERLOCK_CATEGORIES),
                id="sherlock_cat_select",
                prompt="Category")
            yield Select(
                ((d, d) for d in SHERLOCK_DIFFICULTIES),
                id="sherlock_diff_select",
                prompt="Difficulty")
            yield Select(
                (("Active", "active"), ("Retired", "retired"), ("Retired Free", "retired_free")),
                id="sherlock_state_select",
                prompt="State")
            yield Button("Apply")

    def on_mount(self):
        self.filtering = SherlockFilter()

    @on(Select.Changed, "#sherlock_cat_select")
    def cat_changed(self, event):
        self.filtering.category = event.value if event.value != Select.BLANK else ""

    @on(Select.Changed, "#sherlock_diff_select")
    def diff_changed(self, event):
        self.filtering.difficulty = [event.value] if event.value != Select.BLANK else []

    @on(Select.Changed, "#sherlock_state_select")
    def state_changed(self, event):
        self.filtering.state = event.value if event.value != Select.BLANK else ""

    def on_button_pressed(self):
        self.dismiss(self.filtering)


class SherlockDetails(Container):

    CURRENT_ID: int = None
    sherlock_data: dict = None
    tasks_data: list = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sherlock_data = None
        self.tasks_data = []

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("Info", id="sherlock_info_tab"):
                yield Markdown(id="sherlock_text")
                yield Button("Download", id="sherlock_download_button", flat=True)
            with TabPane("Tasks", id="sherlock_tasks_tab"):
                with Horizontal(id="sherlock_tasks_layout"):
                    with Container(id="sherlock_tasks_list_pane"):
                        yield DataTable(id="sherlock_tasks_table")
                    with Container(id="sherlock_task_detail_pane"):
                        with VerticalScroll(id="sherlock_task_detail_scroll"):
                            yield Static(id="sherlock_task_detail")
                        with Horizontal(id="sherlock_submit_container"):
                            yield Input(placeholder="Answer...", id="sherlock_answer_input")
                            yield Button("Submit", id="sherlock_submit_button")

    async def on_mount(self):
        dt = self.query_one("#sherlock_tasks_table", DataTable)
        dt.show_header = True
        dt.cursor_type = "row"
        dt.add_column(label="Task")
        dt.add_column(label="Done")

    def show_sherlock(self, sherlock_id):
        self.app.post_message(EventMsg(f"Sherlock::Show {sherlock_id}"))
        self.CURRENT_ID = sherlock_id
        self.loading = True
        self.run_worker(self._load_sherlock())

    async def _load_sherlock(self):
        if self.CURRENT_ID is None:
            return
        try:
            try:
                profile = await self.app.API.async_get(f"/api/v4/sherlocks/{self.CURRENT_ID}", cache_this=0)
                self.sherlock_data = profile.get("data", {})
            except Exception as e:
                self.sherlock_data = {}
                self.tasks_data = []
                err = str(e)
                if "403" in err:
                    self._render_error("This Sherlock requires VIP access.")
                else:
                    self._render_error(f"Failed to load: {err}")
                self.loading = False
                return

            description = ""
            try:
                info = await self.app.API.async_get(f"/api/v4/sherlocks/{self.CURRENT_ID}/info", cache_this=0)
                info_data = info.get("data", info)
                description = info_data.get("description", "") if isinstance(info_data, dict) else ""
            except Exception as e:
                if "403" in str(e):
                    description = "*This Sherlock requires VIP access to view the description.*"
                else:
                    description = "*Description not available.*"

            self.tasks_data = []
            try:
                tasks = await self.app.API.async_get(f"/api/v4/sherlocks/{self.CURRENT_ID}/tasks", cache_this=0)
                self.tasks_data = tasks.get("data", [])
            except Exception:
                pass

            workdir = self.app.settings.workdir
            self._task_dir = _sherlock_dir(self.sherlock_data.get("name", "unknown"), workdir)

            self._render_info(description)
            self._render_tasks()

            self.border_title = f"{self.CURRENT_ID} :: {self.sherlock_data.get('name', '?')}"
            self.loading = False
            self.refresh()

            ensure_task_dir(self.app, self._task_dir, self._on_dir_ready)
        except Exception as e:
            self.post_message(ErrorMsg(e))

    def _on_dir_ready(self, path):
        self._dir_created = path is not None

    def _render_error(self, message):
        self.query_one("#sherlock_text", Markdown).update(f"## Error\n\n{message}")
        self.query_one("#sherlock_download_button", Button).styles.visibility = "hidden"
        dt = self.query_one("#sherlock_tasks_table", DataTable)
        dt.clear()
        self.border_title = f"{self.CURRENT_ID} :: (access denied)"

    def _render_info(self, description):
        sd = self.sherlock_data
        diff = sd.get('difficulty', '?')
        color = sherlock_difficulty_map.get(diff, '#FFFFFF')

        text = f"# {sd.get('name', '?')}\n\n"
        text += f" - **Difficulty** : [{color}]{diff}[/{color}]\n"
        text += f" - **Category** : {sd.get('category_name', '?')}\n"
        text += f" - **Solves** : {sd.get('user_owns_count', sd.get('solves', '?'))}\n"
        text += f" - **Rating** : {sd.get('rating', '?')}\n"
        text += f" - **State** : {sd.get('state', '?')}\n\n"
        text += f"---\n\n{description}\n"

        completed = sum(1 for t in self.tasks_data if _is_task_completed(t))
        total = len(self.tasks_data)
        text += f"\n\n**Progress** : {completed}/{total} tasks completed\n"

        btn = self.query_one("#sherlock_download_button", Button)
        btn.styles.visibility = "visible" if "download" in sd.get("play_methods", []) else "hidden"

        self.query_one("#sherlock_text", Markdown).update(text)

    def _render_tasks(self):
        dt = self.query_one("#sherlock_tasks_table", DataTable)
        dt.clear()
        for i, task in enumerate(self.tasks_data, 1):
            dt.add_row(
                str(task.get("title", f"# {i}")),
                "✅" if _is_task_completed(task) else "❌",
                key=task["id"],
            )
        self.query_one("#sherlock_task_detail", Static).update("Select a task")

    @on(DataTable.RowSelected, "#sherlock_tasks_table")
    def task_selected(self, event):
        task_id = event.row_key.value
        task = next((t for t in self.tasks_data if t["id"] == task_id), None)
        if not task:
            return
        self.app.post_message(DebugMsg("Sherlock::TaskSelected", task))
        self._render_task_detail(task)
        inp = self.query_one("#sherlock_answer_input", Input)
        mask = task.get("masked_flag", "??")
        inp.placeholder = f"Answer: {mask}"
        inp._task_id = task_id

    def _render_task_detail(self, task):
        info = Table.grid(expand=True)
        info.add_column(ratio=1)
        info.add_column(ratio=3)

        info.add_row("[b]Task", str(task.get("title", "?")))
        info.add_row("[b]State", "✅ Complete" if _is_task_completed(task) else "❌ Incomplete")
        info.add_row("", "")
        info.add_row("[b]Question", "")

        self.query_one("#sherlock_task_detail", Static).update(info)

        desc = task.get("description", "*No description*")
        hint = task.get("hint", "")
        mask = task.get("masked_flag", "")

        detail = self.query_one("#sherlock_task_detail", Static)
        lines = Table.grid(expand=True)
        lines.add_column(ratio=1)
        lines.add_column(ratio=3)
        lines.add_row("[b]Task", str(task.get("title", "?")))
        lines.add_row("[b]State", "✅ Complete" if _is_task_completed(task) else "❌ Incomplete")
        lines.add_row("", "")
        lines.add_row("[b]Description", desc)
        if hint:
            lines.add_row("", "")
            lines.add_row("[b]Hint", hint)
        if mask:
            lines.add_row("", "")
            lines.add_row("[b]Answer format", f"`{mask}`")
        detail.update(lines)

    @on(Button.Pressed, "#sherlock_submit_button")
    async def submit_answer(self, event):
        inp = self.query_one("#sherlock_answer_input", Input)
        task_id = getattr(inp, '_task_id', None)
        answer = inp.value.strip()
        if not task_id or not answer:
            self.app.notify("Select a task and enter an answer", severity="warning")
            return
        try:
            resp = await self.app.API.async_post(
                f"/api/v4/sherlocks/{self.CURRENT_ID}/tasks/{task_id}/flag",
                {"flag": answer}
            )
            msg = resp.get("message", "")
            self.app.post_message(DebugMsg("Sherlock::Submit", answer, resp))
            if "Incorrect" in msg:
                self.app.notify(msg, severity="error")
            else:
                self.app.notify(msg or "Correct!", severity="information")
                inp.value = ""
                self.run_worker(self._load_sherlock())
        except Exception as e:
            err = str(e)
            if "Incorrect" in err or "incorrect" in err:
                self.app.notify("Incorrect flag!", severity="error")
            else:
                self.app.notify(f"Submit failed: {err[:80]}", severity="error")
            self.app.post_message(ErrorMsg(e))

    @on(Button.Pressed, "#sherlock_download_button")
    async def download(self, event):
        if not self.CURRENT_ID or not self.sherlock_data:
            return
        try:
            data = await self.app.API.async_get(
                f"/api/v4/sherlocks/{self.CURRENT_ID}/download_link", cache_this=0)
            url = data.get("url")
            if not url:
                self.app.notify("No download available", severity="warning")
                return
            self.app.post_message(EventMsg(f"Sherlock::Download started"))
            self.app.notify("Downloading...", timeout=3)
            self.run_worker(self._bg_download(url))
        except Exception as e:
            self.app.post_message(ErrorMsg(e))

    async def _bg_download(self, url):
        try:
            sdir = getattr(self, '_task_dir', None)
            if not sdir:
                workdir = self.app.settings.workdir
                sdir = _sherlock_dir(self.sherlock_data.get("name", "unknown"), workdir)
            os.makedirs(sdir, exist_ok=True)
            chall_data = {
                "real_dir_name": os.path.abspath(sdir),
                "file_name": "sherlock.zip",
            }
            result = await async_download_and_extract(
                chall_data, url,
                password=self.app.settings.zip_password,
                unpack_cmd=self.app.settings.unpack_cmd,
            )
            self.app.post_message(EventMsg(f"Sherlock::Download complete: {result}"))
            self.app.notify("Download complete", severity="information")
        except Exception as e:
            self.app.post_message(ErrorMsg(e))
            self.app.notify(f"Download failed: {e}", severity="error")


class SherlockListTable(DataTable):

    PER_PAGE = 30
    _MORE_KEY = "__more__"
    _loading_more = False

    def __init__(self) -> None:
        super().__init__()
        self.loading = True
        self.id = "sherlock_table"
        self.sherlock_data = {}
        self.show_header = True
        self.cursor_type = "row"
        self.current_page = 0
        self.total_pages = 1
        self.filtering = SherlockFilter()

        self.add_column(label="ID")
        self.add_column(label="Name", width=20)
        self.add_column(label="Category")
        self.add_column(label="Difficulty")
        self.add_column(label="Solved")
        self.add_column(label="State")

    def on_data_table_row_selected(self, event):
        if event.control.id != self.id or event.row_key.value == self._MORE_KEY:
            return
        self.app.query_one(SherlockDetails).show_sherlock(event.row_key.value)

    def on_data_table_row_highlighted(self, event) -> None:
        if event.row_key and event.row_key.value == self._MORE_KEY and not self._loading_more:
            self._load_more()

    def _remove_sentinel(self):
        try:
            self.remove_row(self._MORE_KEY)
        except Exception:
            pass

    def _add_sentinel(self):
        self.add_row("", ".... more ....", "", "", "", "", key=self._MORE_KEY)

    def _append_rows(self, items):
        for s in items:
            sid = s["id"]
            if sid in self.sherlock_data:
                continue
            self.sherlock_data[sid] = s
            diff = s.get("difficulty", "?")
            color = sherlock_difficulty_map.get(diff, "#FFFFFF")
            self.add_row(
                str(sid),
                s["name"],
                s.get("category_name", "?"),
                f"[{color}]{diff}[/{color}]",
                "✅" if s.get("is_owned") else f"{s.get('progress', 0)}%",
                s.get("state", "?"),
                key=sid,
            )

    async def _do_load(self):
        try:
            await self.app.API.ensure_init()
            params = []
            params += self.filtering.serialize()
            params.append(("per_page", str(self.PER_PAGE)))
            params.append(("page", str(self.current_page)))
            data = await self.app.API.async_get(
                "/api/v4/sherlocks", params=params, cache_this=0)

            meta = data.get("meta", {})
            self.current_page = meta.get("current_page", 1)
            self.total_pages = meta.get("last_page", 1)

            self._remove_sentinel()
            self._append_rows(data.get("data", []))
            if self.current_page < self.total_pages:
                self._add_sentinel()
            self.loading = False
            self._loading_more = False
            self.app.post_message(EventMsg(
                f"Sherlocks::{len(self.sherlock_data)} loaded (page {self.current_page}/{self.total_pages})"))
        except Exception as e:
            self._loading_more = False
            self.post_message(ErrorMsg(e))

    def _load_more(self):
        if self.current_page >= self.total_pages or self._loading_more:
            return
        self._loading_more = True
        self.current_page += 1
        self.run_worker(self._do_load())

    def reload_list(self, force=0):
        self.current_page = 1
        self.sherlock_data = {}
        self.clear()
        self.loading = True
        self.run_worker(self._do_load())

    async def on_mount(self):
        self.current_page = 1
        self.run_worker(self._do_load())


class ContainerSherlocks(Container):

    BINDINGS = [
        ("f", "filter", "Filter"),
        ("escape", "focus_list", "Focus list"),
    ]

    def action_focus_list(self):
        self.query_one("#sherlock_table").focus()

    def action_filter(self):
        self.app.push_screen(SherlockFilterScreen(), self._filter_callback)

    def _filter_callback(self, result):
        self.app.post_message(DebugMsg("SherlockFilter", str(result)))
        self.query_one("#sherlock_filter_label").update(str(result))
        table = self.query_one("#sherlock_table", SherlockListTable)
        table.filtering = result
        table.reload_list(force=1)

    @on(Button.Pressed)
    def button_clicked(self, event):
        bid = event.button.id
        if bid == "sherlock_reload_button":
            self.query_one("#sherlock_table", SherlockListTable).reload_list(force=1)
        elif bid == "sherlock_filter_button":
            self.action_filter()

    def compose(self) -> ComposeResult:
        with Horizontal(id="sherlock_control"):
            yield Button("Reload", flat=1, id="sherlock_reload_button")
            yield Button("Filter", flat=1, id="sherlock_filter_button")
            yield Label("<no filter>", id="sherlock_filter_label")

        with Container(id="sherlock_content"):
            with Container(id="sherlock_list_pane"):
                yield SherlockListTable()
            yield SherlockDetails(id="sherlock_details_pane")
