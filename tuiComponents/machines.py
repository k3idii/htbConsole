
from textual.widgets import DataTable
from httpApi import HTBApiSession


from textual.containers import Container
from textual.widgets import Label, TabbedContent, TabPane
from textual.app import ComposeResult



from .machineControl import MachineDetails




# provide : CurrentMachines, SeasonalMachines, RetiredMachines 
from tuiComponents.messages import DebugMsg, ErrorMsg, EventMsg


class _PaginatedMachineTable(DataTable):
    """Base class for paginated machine tables with infinite scroll."""

    machine_difficulty_map = {
            "Easy": "#90cd3f",
            "Medium": "#ffb83e",
            "Hard": "#fe0000",
            "Insane": "#ffccff"
        }
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
        self.current_page = 0
        self.total_pages = 1
        self._loading_more = False

        self.add_column(label="ID")
        self.add_column(label="Name", width=20)
        self.add_column(label="OS")
        self.add_column(label="User")
        self.add_column(label="Root")
        self.add_column(label="Points")
        self.add_column(label="Rating")

    def on_data_table_row_selected(self, event) -> None:
        if event.control.id != self.id or event.row_key.value == self._MORE_KEY:
            return
        machine_details = self.app.query_one(MachineDetails)
        if not machine_details.has_active_machine():
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

    def _parse_machine(self, machine):
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

    def _append_rows(self, items):
        for machine in items:
            mid = machine["id"]
            if mid in self.machine_data:
                continue
            mdata = self._parse_machine(machine)
            self.machine_data[mid] = mdata
            diff = mdata['difficulty']
            color = self.machine_difficulty_map.get(diff, "#FFFFFF")
            self.add_row(
                str(mid),
                f"[{color}]{mdata['name']}",
                mdata['os'],
                "✅" if mdata['user_owned'] else "❌",
                "✅" if mdata['root_owned'] else "❌",
                str(mdata['points']),
                str(mdata['rating']),
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
        self.run_worker(self._do_load())

    async def on_mount(self) -> None:
        self.current_page = 1
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

    machine_difficulty_map = {
            "Easy": "#90cd3f",
            "Medium": "#ffb83e",
            "Hard": "#fe0000",
            "Insane": "#ffccff"
        }

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

        self.add_column(label="ID")
        self.add_column(label="Name", width=20)
        self.add_column(label="OS")
        self.add_column(label="User")
        self.add_column(label="Root")
        self.add_column(label="Points")
        self.add_column(label="Rating")

    def on_data_table_row_selected(self, event) -> None:
        if event.control.id != self.id:
            return
        machine_details = self.app.query_one(MachineDetails)
        if not machine_details.has_active_machine():
            mid = int(event.row_key.value)
            if mid in self.machine_data:
                machine_details.set_context(event.row_key.value, self.machine_data[mid])
            else:
                machine_details.clear_context()

    async def on_mount(self) -> None:
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
                self.machine_data[mid] = {
                    "name": machine["name"],
                    "id": mid,
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
                    "is_competitive": True,
                    "user_owns_count": machine.get("user_owns_count", 0),
                    "root_owns_count": machine.get("root_owns_count", 0),
                }
            self.clear()
            for mid, mdata in self.machine_data.items():
                diff = mdata['difficulty']
                color = self.machine_difficulty_map.get(diff, "#FFFFFF")
                self.add_row(
                    str(mid),
                    f"[{color}]{mdata['name']}",
                    mdata['os'],
                    "✅" if mdata['user_owned'] else "❌",
                    "✅" if mdata['root_owned'] else "❌",
                    str(mdata['points']),
                    str(mdata['rating']),
                    key=mid)
            self.loading = False
            self.app.post_message(DebugMsg("SeasonalMachines", machine_count=len(self.machine_data)))
        except Exception as e:
            self.post_message(ErrorMsg(e))
    















class ContainerMachines(Container):

  BINDINGS = [
    ("escape", "focus_list", "Focus list"),
  ]

  def action_focus_list(self):
    try:
      self.query_one("#current_machines").focus()
    except Exception:
      pass

  def compose(self) -> ComposeResult:
    with Container(id="machines_container") as machines_container:
        machines_container.border_title = "Machines"
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
    yield MachineDetails(id="machine_control")
