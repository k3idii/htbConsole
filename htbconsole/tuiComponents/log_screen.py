from textual.screen import Screen
from textual.widgets import RichLog
from textual.containers import Container
from textual.app import ComposeResult


class LogScreen(Screen):

    BINDINGS = [("l", "close_log", "Close"), ("escape", "close_log", "Close")]

    CSS = """
    LogScreen {
        align: center bottom;
    }
    #log_overlay {
        width: 100%;
        height: 100%;
        background: #111927;
        border: panel #3d5276;
        border-title-color: #a4b1cd;
        border-title-style: bold;
        border-title-align: right;
    }
    #log {
        width: 100%;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="log_overlay") as c:
            c.border_title = "Log console  (l / esc to close)"
            yield RichLog(id="log")

    def on_mount(self):
        log = self.query_one("#log", RichLog)
        for msg in getattr(self.app, '_log_buffer', []):
            log.write(msg)

    def action_close_log(self):
        self.app._log_visible = False
        self.app.pop_screen()
