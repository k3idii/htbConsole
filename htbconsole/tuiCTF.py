import asyncio
import os
from datetime import datetime

from textual import on
from textual.binding import Binding
from textual.app import App, ComposeResult
from textual.widgets import RichLog, Footer, Header
from textual.containers import Container

from .tuiComponents.messages import DebugMsg, ErrorMsg, EventMsg, SelfFormattingMsg
from .tuiComponents.token_screen import TokenInputScreen
from .tuiComponents.ctf_list import CTFListView
from .tuiComponents.ctf_challs import CTFChallengesView
from .tuiComponents.log_screen import LogScreen
from .httpApi import HTBCTFSession
from .appSettings import CTFSettings


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

    _LOG_FILE = "ctf_logs.txt"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ctf_cache = {}
        self._current_ctf = None
        self._ctf_challenges = {}
        self._ctf_cats = {}
        self._log_buffer = []
        self._log_visible = False
        self._log_fh = None
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._prompting = False

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

    # --- httpApi log hooks (event / debug / notify) ------------------------

    def api_log_event(self, message):
        self.post_message(EventMsg(message))

    def api_log_debug(self, message, *args, **kwargs):
        self.post_message(DebugMsg(message, *args, **kwargs))

    def api_notify(self, message, severity="information", timeout=5):
        self.notify(message, severity=severity, timeout=timeout)

    def create_session(self, token) -> HTBCTFSession:
        """Build an HTBCTFSession bound to this app's log hooks + workdir cache."""
        workdir = getattr(getattr(self, "settings", None), "workdir", ".")
        session = HTBCTFSession(token, cache_file=os.path.join(workdir, "ctf_cache.json"))
        session._handle_log_event = self.api_log_event
        session._handle_log_debug = self.api_log_debug
        session._handle_notify = self.api_notify
        return session

    def _log_to_file(self, message):
        if not self.settings.save_logs:
            return
        try:
            if not self._log_fh:
                self._log_fh = open(self._LOG_FILE, "a", encoding="utf-8")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log_fh.write(f"[{ts}] {message}\n")
            self._log_fh.flush()
        except Exception:
            pass

    @on(DebugMsg)
    @on(EventMsg)
    @on(ErrorMsg)
    def log_messages(self, message: SelfFormattingMsg) -> None:
        self._log_buffer.append(message)
        self._log_to_file(message)
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
        self.run_worker(self.ensure_init())

    async def ensure_init(self):
        async with self._init_lock:
            if self._initialized:
                return
            self._initialized = await self._validate_token()

    async def _validate_token(self) -> bool:
        try:
            await self.CTF_API.async_get("/api/ctfs")
            self.post_message(EventMsg("CTF token valid"))
            return True
        except Exception as ex:
            self._prompt_for_token(ex)
            return False

    def _prompt_for_token(self, ex):
        if self._prompting:
            return
        self._prompting = True
        self.push_screen(
            TokenInputScreen(
                title="CTF Token Required",
                message=f"Token is missing or invalid: {ex}",
                token_env="CTF_TOKEN",
            ),
            self._on_token_input,
        )

    def _on_token_input(self, token):
        self._prompting = False
        if not token:
            self.exit()
            return
        self.CTF_API = self.create_session(token)
        self._initialized = False
        self.post_message(EventMsg("New CTF token set — validating..."))
        self.run_worker(self.ensure_init())

    def _on_ctf_join(self, result):
        if result is None:
            return
        self.query_one("#ctf_list_view").styles.display = "none"
        self.query_one("#ctf_challenges_view").styles.display = "block"
        self.query_one(CTFChallengesView).load_ctf(result)
        self.post_message(EventMsg(f"Entered CTF: {result['name']}"))

    async def on_unmount(self):
        self.settings.save()
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None
        await self.CTF_API.close()


def main():
    token = os.getenv("CTF_TOKEN", "")
    app = CTFApp()
    app.settings = CTFSettings.load()
    app.CTF_API = app.create_session(token)
    app.run()


if __name__ == "__main__":
    main()
