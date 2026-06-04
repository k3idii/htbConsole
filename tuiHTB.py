import os

from textual import on
from textual.binding import Binding
from textual.app import App, ComposeResult
from textual.widgets import Label, TabbedContent, TabPane, ContentSwitcher, RichLog
from textual.containers import Container, VerticalScroll, HorizontalScroll
from textual.widgets import Footer, Header


from tuiComponents.machines import ContainerMachines
from tuiComponents.challs import ContainerChallenges
from tuiComponents.sherlocks import ContainerSherlocks
from tuiComponents.player import ContainerPlayerInfo
from tuiComponents.settings import ContainerSettings
from tuiComponents.token_screen import TokenInputScreen

from tuiComponents.messages import DebugMsg, ErrorMsg, EventMsg, SelfFormattingMsg
from httpApi import HTBApiSession


class OutputLog(RichLog):
  border_title = "Log console"


class HackTheApp(App):
  API : HTBApiSession
  TERMINAL : str = "/usr/bin/xfce4-terminal --hold -x "
  WORKDIR : str = os.environ.get("HTB_WORKDIR", "./work")
  ZIP_PASSWORD : str = "hackthebox"
  UNPACK_CMD : str = "7z -o./unpacked/ -p{password} x {file}"
  AUTO_CREATE_DIR : bool = True

  CSS_PATH = "HTB.tcss"

  logs_size = 0

  BINDINGS = [
    Binding("q", "quit", "Quit the app", show=True),
    Binding("l", "logs", "Show logs", show=True),
    Binding("[", "prev_tab", "Prev tab", show=True),
    Binding("]", "next_tab", "Next tab", show=True),
  ]

  def action_logs(self):
    self.post_message(EventMsg(f"ToggleLogs {self.logs_size}"))
    self.logs_size = 0 if self.logs_size else 1
    if self.logs_size:
      self.query_one("#container-main").styles.height="80%"
      self.query_one("#container-logs").styles.height="20%"
    else:
      self.query_one("#container-main").styles.height="20%"
      self.query_one("#container-logs").styles.height="80%"

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
    with Container(id="container-logs"):
      yield OutputLog(id="log")
    yield Footer()

  @on(DebugMsg)
  @on(EventMsg)
  @on(ErrorMsg)
  def log_debug_messages(self, message: SelfFormattingMsg) -> None:
      self.query_one("#log").write(message)

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
    os.makedirs(self.WORKDIR, exist_ok=True)
    self.post_message(EventMsg(f"App is ready (workdir: {os.path.abspath(self.WORKDIR)})"))
    self.run_worker(self._validate_token())

  async def _validate_token(self):
    try:
      await self.API.ensure_init()
      name = self.API.CRRENT_USER.get("info", {}).get("name", "?")
      self.post_message(EventMsg(f"Token valid — logged in as {name}"))
    except Exception:
      self.call_from_thread(
        self.push_screen,
        TokenInputScreen(
          title="HTB Token Required",
          message="Token is missing or invalid.",
          token_env="HTB_TOKEN",
        ),
        self._on_token_input,
      ) if not self.is_running else self.push_screen(
        TokenInputScreen(
          title="HTB Token Required",
          message="Token is missing or invalid.",
          token_env="HTB_TOKEN",
        ),
        self._on_token_input,
      )

  def _on_token_input(self, token):
    if not token:
      self.exit()
      return
    self.API = HTBApiSession(token, self)
    self.post_message(EventMsg("New token set — validating..."))
    self.run_worker(self._validate_token())

  async def on_unmount(self) -> None:
    await self.API.close()

  def get_api(self) -> HTBApiSession:
    return self.API


def main():
  token = os.getenv("HTB_TOKEN", "")
  app = HackTheApp()
  app.API = HTBApiSession(token, app)
  app.run()


if __name__ == "__main__":
  main()
