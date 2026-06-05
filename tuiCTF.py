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
from tuiComponents.log_screen import LogScreen
from httpApi import HTBCTFSession
from appSettings import CTFSettings


class CTFApp(App):
    CTF_API: HTBCTFSession
    
    ALLOW_SELECT = True
    CSS_PATH = "CTF.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("l", "logs", "Logs", show=True),
        Binding("escape", "back_to_list", "Back", show=True),
    ]

    SCREENS = {"log": LogScreen}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ctf_cache = {}
        self._current_ctf = None
        self._ctf_challenges = {}
        self._ctf_cats = {}
        self._log_buffer = []
        self._log_visible = False

    def action_logs(self):
        if isinstance(self.screen, LogScreen):
            self._log_visible = False
            self.pop_screen()
        else:
            self.push_screen("log")
            self._log_visible = True

    def action_back_to_list(self):
        self.query_one("#ctf_list_view").styles.display = "block"
        self.query_one("#ctf_challenges_view").styles.display = "none"
        self._current_ctf = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="container-main"):
            yield CTFListView(id="ctf_list_view")
            yield CTFChallengesView(id="ctf_challenges_view")
        yield Footer()

    @on(DebugMsg)
    @on(EventMsg)
    @on(ErrorMsg)
    def log_messages(self, message: SelfFormattingMsg) -> None:
        self._log_buffer.append(message)
        if self._log_visible:
            try:
                self.screen.query_one("#log", RichLog).write(message)
            except Exception:
                pass

    def on_ready(self):
        self.settings = CTFSettings.load()
        os.makedirs(self.settings.workdir, exist_ok=True)
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
        self.settings.save()
        await self.CTF_API.close()


def main():
    token = os.getenv("CTF_TOKEN", "")
    app = CTFApp()
    app.settings = CTFSettings.load()
    app.CTF_API = HTBCTFSession(token, app)
    app.run()


if __name__ == "__main__":
    main()
