import os

from textual import on
from textual.binding import Binding
from textual.app import App, ComposeResult
from textual.widgets import RichLog, Footer, Header
from textual.containers import Container

from tuiComponents.messages import DebugMsg, ErrorMsg, EventMsg, SelfFormattingMsg
from tuiComponents.token_screen import TokenInputScreen
from tuiComponents.ctf_list import CTFListView
from tuiComponents.ctf_challs import CTFChallengesView
from httpApi import HTBCTFSession


class OutputLog(RichLog):
    border_title = "Log console"


class CTFApp(App):
    CTF_API: HTBCTFSession
    WORKDIR: str = os.environ.get("HTB_WORKDIR", "./work")
    ZIP_PASSWORD: str = "hackthebox"
    UNPACK_CMD: str = "7z -o./unpacked/ -p{password} x {file}"

    CSS_PATH = "CTF.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("l", "logs", "Logs", show=True),
        Binding("escape", "back_to_list", "Back", show=True),
    ]

    logs_size = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ctf_cache = {}
        self._current_ctf = None
        self._ctf_challenges = {}
        self._ctf_cats = {}

    def action_logs(self):
        self.logs_size = 0 if self.logs_size else 1
        if self.logs_size:
            self.query_one("#container-main").styles.height = "80%"
            self.query_one("#container-logs").styles.height = "20%"
        else:
            self.query_one("#container-main").styles.height = "20%"
            self.query_one("#container-logs").styles.height = "80%"

    def action_back_to_list(self):
        self.query_one("#ctf_list_view").styles.display = "block"
        self.query_one("#ctf_challenges_view").styles.display = "none"
        self._current_ctf = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="container-main"):
            yield CTFListView(id="ctf_list_view")
            yield CTFChallengesView(id="ctf_challenges_view")
        with Container(id="container-logs"):
            yield OutputLog(id="log")
        yield Footer()

    @on(DebugMsg)
    @on(EventMsg)
    @on(ErrorMsg)
    def log_messages(self, message: SelfFormattingMsg) -> None:
        self.query_one("#log").write(message)

    def on_ready(self):
        os.makedirs(self.WORKDIR, exist_ok=True)
        self.query_one("#ctf_challenges_view").styles.display = "none"
        self.post_message(EventMsg("CTF App ready"))
        self.run_worker(self._validate_token())

    async def _validate_token(self):
        try:
            await self.CTF_API.get("/api/ctfs")
            self.post_message(EventMsg("CTF token valid"))
        except Exception:
            self.push_screen(
                TokenInputScreen(
                    title="CTF Token Required",
                    message="Token is missing or invalid.",
                    token_env="CTF_TOKEN",
                ),
                self._on_token_input,
            )

    def _on_token_input(self, token):
        if not token:
            self.exit()
            return
        self.CTF_API = HTBCTFSession(token, self)
        self.post_message(EventMsg("New CTF token set — validating..."))
        self.run_worker(self._validate_token())

    def _on_ctf_join(self, result):
        if result is None:
            return
        self.query_one("#ctf_list_view").styles.display = "none"
        self.query_one("#ctf_challenges_view").styles.display = "block"
        self.query_one(CTFChallengesView).load_ctf(result)
        self.post_message(EventMsg(f"Entered CTF: {result['name']}"))

    async def on_unmount(self):
        await self.CTF_API.close()


def main():
    token = os.getenv("CTF_TOKEN", "")
    app = CTFApp()
    app.CTF_API = HTBCTFSession(token, app)
    app.run()


if __name__ == "__main__":
    main()
