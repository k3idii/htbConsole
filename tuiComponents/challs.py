

from textual import system_commands
from textual import system_commands
import re 
import os

from textual.widgets import DataTable
from httpApi import HTBApiSession
from textual.widgets import Button, Sparkline, Label, DirectoryTree, Input, Select, Markdown, TabbedContent, TabPane

from textual.screen import ModalScreen

from textual import on
from textual.containers import Container, VerticalScroll, Horizontal
from textual.app import ComposeResult

from .messages import DebugMsg, ErrorMsg, EventMsg
from .downloader import async_download_and_extract, execute_shell
from .notes_editor import NotesEditor
from .confirm_dir import ensure_task_dir

import jinja2
from urllib.parse import quote as _urlquote

def _gen_url(protocol="cmd"):
  def _url_builder(*args):
      """Jinja2 helper: cmd('netcat', '10.10.10.1', '80') -> cmd://netcat%2010.10.10.1%2080"""
      parts = [str(a) for a in args if a is not None]
      raw = ' '.join(parts)
      return f"{protocol}://{_urlquote(raw, safe='')}"
  return _url_builder  
 
class CustomUriDispatcher:

  def __init__(self, app):
    self.app = app

  def dispatch(self, uri):
    try:
      proto, content = uri.split("://", 1)
    except Exception: 
      self.app.post_message(EventMsg(f"dispatch: {uri}"))
      return
    self.app.post_message(EventMsg(f"dispatch: {uri}"))
    method = getattr(self,f"_run_{proto}", None)
    
    if method and callable(method):
      try:
        self.app.notify(f"Executing: {proto} {content}", timeout=1, severity="information")
        result = method(content)
        if result is not None:
          self.app.post_message(EventMsg(result))
      except Exception as ex:
        self.app.notify(f"Error@executing: {ex}", timeout=3, severity="error")
        self.app.post_message(ErrorMsg(ex))

  def _run_cmd(self, args):
    self.app.post_message(EventMsg(f"exec: {args}"))
    out = execute_shell(args)

  def _run_terminal(self, args):
    self.app.post_message(EventMsg(f"terminal: {args}"))
    cmd = f"""{self.app.settings.terminal} {args}"""
    out = execute_shell(cmd)


_jinja_env = jinja2.Environment(undefined=jinja2.Undefined)
_jinja_env.globals["cmd"] = _gen_url("cmd")
_jinja_env.globals["terminal"] = _gen_url("terminal")
 

_template_cache = {}

MOCK_TASK_CONTEXT = {
    "name": "ExampleChallenge",
    "difficulty": "Medium",
    "solves": 42,
    "state": "live",
    "description": "Example challenge description",
    "category_name": "Web",
    "local_dir_name": "./work/ExampleChallenge",
    "real_dir_name": "/home/user/work/ExampleChallenge",
    "play_info": {
        "ip": "10.10.10.1",
        "ports": [80, 443],
        "status": "ready",
    },
}


def render_custom_actions(template_src, task_context):
    if template_src not in _template_cache:
        _template_cache[template_src] = _jinja_env.from_string(template_src.strip())
    tmpl = _template_cache[template_src]
    return tmpl.render(task_context)


class ChallengeCategories:

  def __init__(self) -> None:
    self.id_to_name = {}
    self.name_to_id = {}

  async def load(self, api_session):
    data = await api_session.async_get("/api/v4/challenge/categories/list")
    for cat in data.get("info", []):
      cat_id = cat.get("id")
      cat_name = cat.get("name")
      self.id_to_name[cat_id] = cat_name
      self.name_to_id[cat_name] = cat_id

  def __repr__(self):
    return f"ChallengeCategories({list(self.name_to_id.keys())})"


async def _ensure_categories(app):
  if getattr(app, '_challenge_categories', None) is None:
    cats = ChallengeCategories()
    await cats.load(app.API)
    app._challenge_categories = cats
    app.post_message(DebugMsg("Loaded challenge categories", cats))
  return app._challenge_categories


chall_difficulty_map = {
  "Very Easy": "#90ff3f",
  "Easy": "#90cd3f",
  "Medium": "#ffb83e",
  "Hard": "#fe0000",
  "Insane": "#ffccff"
}

pattern1 = re.compile('[^0-9a-zA-Z_]+')

def make_dirname(chall, workdir):
  clean = lambda s: pattern1.sub('',s.lower())
  cat  = clean(chall['category_name'])
  dif  = clean(chall['difficulty'])
  name = clean(chall['name'])
  return os.path.join(workdir, 'challenges', cat, f"{dif}__{name}")


class FlagAcceptedScreen(ModalScreen):

  CSS = """
  FlagAcceptedScreen {
    align: center middle;
  }
  #solved {
    width:50%;
    height: auto;
  }
  """

  def compose(self) -> ComposeResult:
    with Container(id="solved"):
      yield Label("Task solved !")
      yield Button("Close")

  def on_button_pressed(self):
    self.dismiss(None)

        
 

class ChallDetails(Container):
  """Static widget that shows the challenge details."""

  CURRENT_ID : int = None
  chall_data : dict = None
  action_templates = None

  def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self.chall_data = None
    self._writeup_loaded_for = None

  def on_mount(self):
    workdir = self.app.settings.workdir
    os.makedirs(workdir, exist_ok=True)
    self.query_one("#chall_dir_tree", DirectoryTree).path = os.path.abspath(workdir)

  def has_active_chall(self) -> bool:
    """Check if there is an active challenge."""
    return self.chall_data is not None

  def set_context(self, chall_id: str, chall_data: dict) -> None:
    """Set the context of the challenge details."""
    self.chall_data = chall_data
    self.refresh()

 
  async def do_download(self):
    id = self.CURRENT_ID
    data = await self.app.API.async_get(f"/api/v4/challenges/{id}/download_link", cache_this=0)
    url = data['url']
    self.app.post_message(EventMsg(f"Download started: {self.chall_data.get('name', id)}"))
    self.app.notify("Downloading...", timeout=3)
    self.run_worker(self._bg_download(url))

  async def _bg_download(self, url):
    try:
      result = await async_download_and_extract(
        self.chall_data, url,
        password=self.app.settings.zip_password,
        unpack_cmd=self.app.settings.unpack_cmd,
      )
      self.app.post_message(EventMsg(f"Download complete: {result}"))
      self.app.notify("Download complete", severity="information")
      try:
        self.query_one("#chall_dir_tree").reload()
      except Exception:
        pass
    except Exception as e:
      self.app.post_message(ErrorMsg(e))
      self.app.notify(f"Download failed: {e}", severity="error")
           
  async def do_start_box(self):
    self.app.post_message(EventMsg(f"Challenge::START {self.CURRENT_ID}"))
    rsp = await self.app.API.async_post(
      "/api/v4/container/start",
      {"containerable_id": self.CURRENT_ID}
    )
    return rsp
    
    # POST https://labs.hackthebox.com/api/v4/container/start
    # {"containerable_id":1054}
    # -> {"message":"Instance Created!","id":2163214}
  
  async def do_stop_box(self):
    self.app.post_message(EventMsg(f"Challenge::STOP {self.CURRENT_ID}"))
    rsp = await self.app.API.async_post(
      "/api/v4/container/stop",
      {"containerable_id": self.CURRENT_ID}
    )
    return rsp
    # https://labs.hackthebox.com/api/v4/container/stop
    # <- {"containerable_id":1054}
    # -> {"message":"Container Stopped"}

  
  async def do_start_stop_box(self):
    if self._is_box_running():
      resp = await self.do_stop_box()
    else:
      resp = await self.do_start_box()
    self.app.post_message(DebugMsg("Challenge::start_stop", resp))
    await self._reload_panel_worker()
    

  async def do_submit_flag(self):
    flag = str(self.app.query_one("#chall_submit_flag_input").value)
    if len(flag)<2:
      return 0
    try:
      resp = await self.app.API.async_post(
        f"/api/v4/challenge/own",
        {"challenge_id": self.CURRENT_ID, "flag":flag}
      )
      self.app.post_message(DebugMsg("Challenge::submit", flag, resp))
      msg = resp.get("message", "")
      self.app.query_one("#chall_submit_flag_input").value = ''

      if msg == "Incorrect flag":
        self.app.notify("Incorrect flag", severity="error")
        return

      widget : NotesEditor = self.query_one("#chall_notes_editor")
      widget.text += f"\nFLAG : `{flag}`\n"
      the_list : ChallListTable = self.app.query_one("#chall_table")
      the_list.reload_chall_list(force=1)
      self.app.push_screen(FlagAcceptedScreen())

    except Exception as ex:
      err = str(ex)
      if "Incorrect" in err or "incorrect" in err:
        self.app.notify("Incorrect flag!", severity="error")
      else:
        self.app.notify(f"Submit failed: {err[:80]}", severity="error")
      self.app.post_message(ErrorMsg(ex))

  def upadate_title(self, new_title):
    self.border_title = new_title
  
  async def _reload_panel_worker(self):
    if self.CURRENT_ID is None:
      return
    self.app.post_message(EventMsg(f"ChallDetails::Reloading chall {self.CURRENT_ID} details..."))
    try:
      data = await self.app.API.async_get(f"/api/v4/challenge/info/{self.CURRENT_ID}", cache_this=0)
      data = data['challenge']
      self.chall_data = data
      workdir = self.app.settings.workdir
      self.chall_data['local_dir_name'] = make_dirname(self.chall_data, workdir)
      self.chall_data['real_dir_name'] = os.path.abspath(self.chall_data['local_dir_name'])

      ensure_task_dir(self.app, self.chall_data['real_dir_name'], self._finish_reload_panel)
    except Exception as e:
      self.post_message(ErrorMsg(e))

  def _finish_reload_panel(self, path):
    try:
      self.chall_data['_dir_exists'] = path is not None
      self.upadate_title(f"{self.CURRENT_ID} :: {self.chall_data.get('name','!??!?')}")
      self._reload_task_info()
      tree = self.query_one("#chall_dir_tree", DirectoryTree)
      if path is not None:
        self._reload_notes_info()
        tree.path = path
      else:
        tree.path = self.app.settings.workdir
      tree.reload()
      self._reload_cmd()
      self._writeup_loaded_for = None
      self.loading = False
      self.refresh()
      self.app.post_message(EventMsg(f"ChallDetails::Chall {self.CURRENT_ID} details reloaded."))
    except Exception as e:
      self.post_message(ErrorMsg(e))
    
  def _is_box_running(self):
    play_info = self.chall_data.get('play_info')
    if not play_info or not isinstance(play_info, dict):
      return False
    return play_info.get('status') == "ready"

  def _update_start_stop(self):
    if self._is_box_running():
      self.query_one("#chal_start_stop_button").label = "STOP !"
    else:
      self.query_one("#chal_start_stop_button").label = "START !"
      
      
  def _reload_task_info(self):
    text = ''
    text += f" - **Difficulty** : {self.chall_data['difficulty']}\n"
    text += f" - **Solves** : {self.chall_data['solves']}\n"
    text += f" - **State** : {self.chall_data['state']}\n\n"
    text += f" ```{self.chall_data['description']}``` \n\n "

    btn = self.app.query_one("#chall_download_button", Button)
    btn.styles.visibility = "hidden"
    if 'download' in self.chall_data['play_methods']:
      text += f"- **Download** : {self.chall_data['file_name']}\n"
      btn.styles.visibility = "visible"       
    
    btn = self.app.query_one("#chal_start_stop_button", Button)
    btn.styles.visibility = "hidden"
    if 'container' in self.chall_data['play_methods']:
      text += f"- **Container Available** : "
      btn.styles.visibility = "visible"
      
      box_text = '?'
      if self._is_box_running():
        box_text = f"{self.chall_data['play_info']['ip']}:{self.chall_data['play_info']['ports']}"
        self.query_one("#chal_start_stop_button").label = "STOP !"
        self.app.post_message(DebugMsg("Container +", self.chall_data['play_info'], box_text))
      else:
        box_text = "`not running`"
        self.query_one("#chal_start_stop_button").label = "START !"
        self.app.post_message(DebugMsg("Container -", self.chall_data['play_info'], box_text))
      
      text += box_text
      text += "\n"

    text += "\n**Custom actions**\n\n"
    try:
      src = getattr(self.app.settings, 'custom_actions', '')
      text += render_custom_actions(src, self.chall_data)
      self.app.post_message(EventMsg(f"Custom actions rendered : {src} -> {text}")) 
    except Exception as ex:
      text += f"*Error rendering custom actions: {ex}*"
  
    #self.update_text(text)
    self.query_one("#chall_text", Markdown).update(text)

  def _reload_notes_info(self):
    note_file = os.path.join(self.chall_data['local_dir_name'], "NOTES.md")
    widget : NotesEditor = self.query_one("#chall_notes_editor")
    widget.set_filepath(note_file)
    
    
  def _reload_cmd(self):
    pass

  def _reload_writeup(self):
    self._writeup_loaded_for = self.CURRENT_ID
    self.run_worker(self._load_writeup())

  async def _load_writeup(self):
    md = self.query_one("#chall_writeup_content", Markdown)
    if not self.CURRENT_ID:
      md.update("*Select a challenge first*")
      return
    try:
      data = await self.app.API.async_get(f"/api/v4/challenge/{self.CURRENT_ID}/writeup", cache_this=0)
      writeups = data.get("data", [])
      if not writeups:
        md.update("*No community writeups available.*")
        return
      text = "## Community Writeups\n\n"
      for w in writeups:
        author = w.get("username", w.get("author", "?"))
        url = w.get("url", "#")
        title = w.get("title", "Writeup")
        text += f"- **{title}** by {author} — [{url}]({url})\n"
      md.update(text)
    except Exception as e:
      if "403" in str(e):
        md.update("*Writeups available after solving this challenge.*")
      elif "404" in str(e):
        md.update("*No writeups found.*")
      else:
        md.update(f"*Error loading writeups: {e}*")

  async def _download_official_writeup(self):
    if not self.CURRENT_ID:
      return
    try:
      data = await self.app.API.async_get(f"/api/v4/challenge/{self.CURRENT_ID}/writeup/official", cache_this=0)
      url = data.get("url")
      if url:
        self.app.post_message(EventMsg(f"Official writeup: {url}"))
        self.app.notify(f"Official PDF: {url}", timeout=8)
        from .downloader import async_download
        workdir = self.app.settings.workdir
        out_dir = os.path.join(workdir, 'writeups')
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"chall_{self.CURRENT_ID}_official.pdf")
        await async_download(url, out_file)
        self.app.notify(f"Saved to {out_file}", severity="information")
      else:
        self.app.notify("No official writeup available", severity="warning")
    except Exception as e:
      if "403" in str(e):
        self.app.notify("Official writeup requires VIP or solving the challenge", severity="warning")
      else:
        self.app.post_message(ErrorMsg(e))
  
  
  def reload_panel(self):
    self.loading = True
    self.run_worker(self._reload_panel_worker())
  
  def show_chall(self, chall_id) -> "ChallDetails":
    """Show challenge details."""
    self.app.post_message(EventMsg(f"ChallDetails::Show chall {chall_id}"))
    self.CURRENT_ID = chall_id
    self.reload_panel()
  
  @on(Markdown.LinkClicked)
  async def link_was_clicked(self, ev:Markdown.LinkClicked):
    try:
      widget = ev.control
      link = ev.href
      self.app.post_message(DebugMsg(f"LinkClick:{link}",ev,widget,link))
      dispatcher = CustomUriDispatcher(self.app)
      return dispatcher.dispatch(link)
    except Exception as ex:
      self.app.post_message(ErrorMsg(ex))
  
  
  @on(Button.Pressed)
  async def action_start_stop(self, ev):
    self.app.post_message(DebugMsg("Button press",ev.button ))
    id = ev.button.id
    if id == 'chal_start_stop_button':
      await self.do_start_stop_box()
    if id == 'chall_download_button':
      await self.do_download()
    if id == 'chall_submit_flag_button':
      await self.do_submit_flag()
    if id == 'chall_writeup_official_button':
      self.run_worker(self._download_official_writeup())

  @on(TabbedContent.TabActivated, "#chall_detail_tabs")
  def _on_detail_tab(self, event):
    if event.pane.id == "tab_chall_writeup" and self.CURRENT_ID and self._writeup_loaded_for != self.CURRENT_ID:
      self._reload_writeup()

  def compose(self) -> ComposeResult:

    with TabbedContent(id="chall_detail_tabs"):
      with TabPane("Task", id=f"tab_chall_task"):
        yield Sparkline(id="chall_sparkline")
        yield Markdown(id="chall_text",open_links=False)
        
        with Container(id="chall_submit_flag_container"):
          yield Input(placeholder="Submit Flag", id="chall_submit_flag_input")
          yield Button("Submit Flag", id="chall_submit_flag_button")
            
        with Container(id="chall_control_buttons"):
          yield Button("Start/Stop", id="chal_start_stop_button", flat=True, )
          yield Button("Download", id="chall_download_button", flat=True, )
            
      with TabPane("Notes", id=f"tab_chall_notes"):
        yield Label("Notes here  <ctrl+s> to save", id="chall_notes_path")
        yield NotesEditor("", id="chall_notes_editor")
         
      with TabPane("Files", id=f"tab_chall_files"):
        yield DirectoryTree("./work", id="chall_dir_tree")
      with TabPane("Writeup", id=f"tab_chall_writeup"):
        yield Button("Official PDF", id="chall_writeup_official_button", flat=True)
        yield Markdown(id="chall_writeup_content")

 
 
 
 
# ready to cold multiple filters. using single for now ... :)
class ChallFilterThing:
  name = None
  difficulty = None
  category = None
  def __init__(self):
    self.name = ''
    self.difficulty = []
    self.category = []
  
  def sterialize(self):
    val = []
    if self.name:
      val.append( ("name", self.name) )
    for item in self.difficulty:
      val.append( ("difficulty[]" , item.lower() ) )
    for item in self.category:
      val.append( ("category[]"   , str(item)))
    return val
  
  def describe(self, categories_map=None):
    parts = []
    if self.name:
      parts.append(f'"{self.name}"')
    if self.difficulty:
      parts.append(", ".join(self.difficulty))
    if self.category and categories_map:
      names = [categories_map.get(c, str(c)) for c in self.category]
      parts.append(", ".join(names))
    elif self.category:
      parts.append(", ".join(str(c) for c in self.category))
    return " | ".join(parts) if parts else "<no filter>"

  def __repr__(self):
    return self.describe()
  


# TO BE TESTED : 
class ChallFilterScreen(ModalScreen):
  
  CSS = """
  ChallFilterScreen {
    align: center middle;
  }
  #filter_popup {
    width:50%;
    height: auto;
  }
  """
  filtering : ChallFilterThing = ChallFilterThing()
  
  def compose(self) -> ComposeResult:
    with Container(id="filter_popup"):
      yield Label("Filter Challanges")
      yield Input(placeholder="Challenge name ...", id="chall_search_input")
      cats = getattr(self.app, '_challenge_categories', None)
      cat_list = cats.name_to_id.items() if cats else []
      yield Select(
        ( (name, id) for name, id in cat_list ), 
        id="chall_caltegory_selection", 
        prompt="Select Category")
      
      dif_list =  chall_difficulty_map.keys() 
      yield Select(
        ( (key , key) for key in dif_list),
        id="chall_difficulty_selection", 
        prompt="Select Difficulty"
      )
      yield Button("Close")
  
  def on_mount(self):
    self.filtering = ChallFilterThing()

  def on_button_pressed(self):
    self.filtering.name = self.query_one("#chall_search_input").value.strip()
    self.dismiss(self.filtering)

        
  @on(Select.Changed, "#chall_caltegory_selection")
  def category_changed(self, event: Select.Changed) -> None:
    """Handle category selection change."""
    self.filtering.category = [event.value] if event.value != Select.BLANK else []
    self.app.post_message(DebugMsg(f"ChallFilter::Category changed", event, str(self.filtering)))
 
  @on(Select.Changed, "#chall_difficulty_selection")
  def difficulty_changed(self, event: Select.Changed) -> None:
    """Handle difficulty selection change."""
    self.filtering.difficulty = [event.value] if event.value != Select.BLANK else []
    self.app.post_message(DebugMsg(f"ChallFilter::Difficulty changed", event, str(self.filtering)))
  
  
  
 
  
class ChallListTable(DataTable):

  filtering : ChallFilterThing
  PER_PAGE = 30
  _MORE_KEY = "__more__"
  _loading_more = False

  def __init__(self, id) -> None:
    super().__init__()
    self.loading = True
    self.id = id
    self.chall_data = {}
    self.show_header = True
    self.cursor_type = "row"
    self.filtering = ChallFilterThing()
    self.current_page = 0
    self.total_pages = 1

    self.add_column(label="ID")
    self.add_column(label="Name", width=20)
    self.add_column(label="Category")
    self.add_column(label="Difficulty")
    self.add_column(label="Solved")
    self.add_column(label="State")

  def on_data_table_row_selected(self, event) -> None:
    if event.row_key.value == self._MORE_KEY:
      return
    chall_id = event.row_key.value
    self.app.query_one(ChallDetails).show_chall(chall_id)

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

  async def _fetch_page(self):
    filter_params = []
    filter_params += self.filtering.sterialize()
    filter_params.append(("per_page", str(self.PER_PAGE)))
    filter_params.append(("page", str(self.current_page)))

    data = await self.app.API.async_get(
      "/api/v4/challenges", params=filter_params, cache_this=0)

    meta = data.get("meta", {})
    self.current_page = meta.get("current_page", 1)
    self.total_pages = meta.get("last_page", 1)
    return data.get("data", [])

  def _append_rows(self, items):
    for chall in items:
      if chall['id'] in self.chall_data:
        continue
      self.chall_data[chall['id']] = chall
      difficulty_color = chall_difficulty_map.get(chall['difficulty'], "#FFFFFF")
      cats = getattr(self.app, '_challenge_categories', None)
      cat_name = cats.id_to_name.get(chall['category_id'], "Unknown") if cats else "Unknown"
      self.add_row(
        str(chall['id']),
        chall['name'],
        f"{cat_name}",
        f"[{difficulty_color}]{chall['difficulty']}[/{difficulty_color}]",
        "✅" if chall['is_owned'] else "❌",
        chall['state'],
        key=chall['id'],
      )

  async def _do_load(self):
    try:
      await self.app.API.ensure_init()
      items = await self._fetch_page()
      self._remove_sentinel()
      self._append_rows(items)
      if self.current_page < self.total_pages:
        self._add_sentinel()
      self.loading = False
      self._loading_more = False
      self.app.post_message(EventMsg(
        f"ChallList::{len(self.chall_data)} loaded (page {self.current_page}/{self.total_pages})"))
    except Exception as e:
      self._loading_more = False
      self.post_message(ErrorMsg(e))

  def _load_more(self):
    if self.current_page >= self.total_pages or self._loading_more:
      return
    self._loading_more = True
    self.current_page += 1
    self.run_worker(self._do_load())

  def reload_chall_list(self, force=0) -> None:
    self.current_page = 1
    self.chall_data = {}
    self.clear()
    self.loading = True
    self.run_worker(self._do_load())

  async def on_mount(self) -> None:
    self.current_page = 1
    self.run_worker(self._do_load())
    


class ContainerChallenges(Container):

  BINDINGS = [
    ("f", "filter", "Filter tasks"),
    ("escape", "focus_list", "Focus list"),
  ]

  async def on_mount(self):
    self.run_worker(self._load_categories())

  async def _load_categories(self):
    try:
      await _ensure_categories(self.app)
    except Exception as e:
      self.post_message(ErrorMsg(e))

  def action_focus_list(self):
    self.query_one("#chall_table").focus()

  def action_filter(self):
    self.app.post_message(EventMsg("Filtering"))
    # ONE WAY :
    self.app.push_screen(ChallFilterScreen(), self.filter_callback)
 
  def filter_callback(self, result):
    cats = getattr(self.app, '_challenge_categories', None)
    cat_map = cats.id_to_name if cats else {}
    label = result.describe(cat_map)
    self.app.post_message(DebugMsg("Filtering callback", label))
    self.query_one("#chal_filter_label").update(label)

    the_list : ChallListTable = self.query_one("#chall_table")
    the_list.filtering = result
    the_list.reload_chall_list()
    
    
  @on(Button.Pressed)
  def button_clicked(self, event):
    bid = event.button.id
    if bid == 'show_chall_filter_button':
      self.action_filter()
    if bid == "show_chall_reload_button":
      self.query_one("#chall_table", ChallListTable).reload_chall_list(force=1)

  def compose(self) -> ComposeResult:
    with Horizontal(id="chall_filter_control"):
      yield Button("Reload", flat=1, id="show_chall_reload_button")
      yield Button("Filter", flat=1, id="show_chall_filter_button")
      yield Label("<no filter>", id="chal_filter_label")

    with Container(id="chall_content"):
      with Container(id="chall_list_pane"):
        yield ChallListTable(id="chall_table")
      yield ChallDetails(id="chall_details_pane")