import os
import asyncio

from textual import on
from textual.binding import Binding
from textual.app import App, ComposeResult
from textual.widgets import TabbedContent, TabPane, RichLog
from textual.containers import Container
from textual.widgets import Footer, Header


from .tuiComponents.machines import ContainerMachines
from .tuiComponents.challs import ContainerChallenges
from .tuiComponents.sherlocks import ContainerSherlocks
from .tuiComponents.player import ContainerPlayerInfo
from .tuiComponents.settings import ContainerSettings
from .tuiComponents.token_screen import TokenInputScreen
from .tuiComponents.log_screen import LogScreen

from .tuiComponents.messages import DebugMsg, ErrorMsg, EventMsg, SelfFormattingMsg
from .httpApi import HTBApiSession
from .appSettings import HTBSettings


class HackTheApp(App):
  API : HTBApiSession

  ALLOW_SELECT = True  
  CSS_PATH = "HTB.tcss"
  CURRENT_USER = None

  BINDINGS = [
    Binding("q", "quit", "Quit the app", show=True),
    Binding("l", "logs", "Show logs", show=True),
    Binding("[", "prev_tab", "Prev tab", show=True),
    Binding("]", "next_tab", "Next tab", show=True),
  ]

  SCREENS = {"log": LogScreen}

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._log_buffer = []
    self._log_visible = False
    self.active_machine_id = None
    self.active_machine_info = None

    # init gate: held until the token is validated (see ensure_init / on_ready)
    self._init_lock = asyncio.Lock()
    self._initialized = False
    self._prompting = False

    token = os.getenv("HTB_TOKEN", "")
    self.settings = HTBSettings.load()
    self.API = self.create_session(token)
  
  
  def create_session(self, token) -> HTBApiSession:
    """Build an HTBApiSession bound to this app's log hooks + workdir cache."""
    workdir = getattr(self.settings , "workdir", "./")
    session = HTBApiSession(token, cache_file=os.path.join(workdir, "htb_cache.json"))
    session._handle_log_event = self.api_log_event
    session._handle_log_debug = self.api_log_debug
    session._handle_notify = self.api_notify
    return session


  def action_logs(self):
    if isinstance(self.screen, LogScreen):
      self._log_visible = False
      self.pop_screen()
    else:
      self.push_screen("log")
      self._log_visible = True

  def compose(self) -> ComposeResult:
    yield Header(show_clock=True)

    panels = [
      [ "Account",    "account",   ContainerPlayerInfo, ],
      [ "Challenges", "challs",    ContainerChallenges, ],
      [ "Sherlocks",  "sherlocks", ContainerSherlocks,  ],
      [ "Machines",   "machines",  ContainerMachines,   ],
      [ "Settings",   "settings",  ContainerSettings,   ],
    ]

    with Container(id="container-main"):
      with TabbedContent(id="main_tabs"):
        for title, id, widget in panels:
          with TabPane(title, id=f"tab__{id}"):
            yield widget(id=f'cont__{id}')
    yield Footer()

  # --- httpApi log hooks (event / debug / notify) ---------------------------

  def api_log_event(self, message):
    self.post_message(EventMsg(message))

  def api_log_debug(self, message, *args, **kwargs):
    self.post_message(DebugMsg(message, *args, **kwargs))

  def api_notify(self, message, severity="information", timeout=5):
    self.notify(message, severity=severity, timeout=timeout)

  @on(DebugMsg)
  @on(EventMsg)
  @on(ErrorMsg)
  def log_debug_messages(self, message: SelfFormattingMsg) -> None:
    self._log_buffer.append(message)
    if self._log_visible:
      try:
        self.screen.query_one("#log", RichLog).write(message)
      except Exception:
        pass

  @on(TabbedContent.TabActivated, "#main_tabs")
  def on_main_tab_activated(self, event: TabbedContent.TabActivated):
    if event.pane.id == "tab__machines":
      self.query_one(ContainerMachines).activate()

  _TAB_IDS = ["tab__account", "tab__challs", "tab__sherlocks", "tab__machines", "tab__settings"]

  def action_prev_tab(self):
    tabs = self.query_one("#main_tabs", TabbedContent)
    try:
      idx = self._TAB_IDS.index(tabs.active)
    except ValueError:
      idx = 0
    tabs.active = self._TAB_IDS[(idx - 1) % len(self._TAB_IDS)]

  def action_next_tab(self):
    tabs = self.query_one("#main_tabs", TabbedContent)
    try:
      idx = self._TAB_IDS.index(tabs.active)
    except ValueError:
      idx = 0
    tabs.active = self._TAB_IDS[(idx + 1) % len(self._TAB_IDS)]

  def on_ready(self) -> None:
    self.settings = HTBSettings.load()
    os.makedirs(self.settings.workdir, exist_ok=True)
    self.post_message(EventMsg(f"App is ready (workdir: {os.path.abspath(self.settings.workdir)})"))
    self.run_worker(self.ensure_init())

  async def ensure_init(self):
    """Block callers until the token is validated.

    The init lock is held while validating and released once done, so any widget
    awaiting ``ensure_init`` proceeds only after on_ready has a valid token.
    """
    async with self._init_lock:
      if self._initialized:
        return
      self._initialized = await self._validate_token()

  async def _validate_token(self) -> bool:
    try:
      result = await self.API.async_get("/api/v4/user/info")
      name = result['info']['name']
      if name is None:
        raise ValueError(f"user info is not returned -> token is invalid : {result}")
      self.CURRENT_USER = result
      self.post_message(EventMsg(f"Token valid — logged in as {name}"))
      return True
    except Exception as ex:
      self._prompt_for_token(ex)
      return False

  def _prompt_for_token(self, ex):
    if self._prompting:
      return
    self._prompting = True
    screen = TokenInputScreen(
      title="HTB Token Required",
      message=f"Token is missing or invalid :{ex}",
      token_env="HTB_TOKEN",
    )
    if not self.is_running:
      self.call_from_thread(self.push_screen, screen, self._on_token_input)
    else:
      self.push_screen(screen, self._on_token_input)

  def _on_token_input(self, token):
    self._prompting = False
    if not token:
      self.exit()
      return
    self.API = self.create_session(token)
    self._initialized = False
    self.post_message(EventMsg("New token set — validating..."))
    self.run_worker(self.ensure_init())

  async def on_unmount(self) -> None:
    self.settings.save()
    await self.API.close()

  def get_api(self) -> HTBApiSession:
    return self.API


def main():
  app = HackTheApp()
  app.run()


if __name__ == "__main__":
  main()
