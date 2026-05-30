from rich.table import Table
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static, ProgressBar, Label
from textual.containers import Container, VerticalScroll

from textual.widgets import DataTable, Static



from httpApi import HTBApiSession
from tuiComponents.messages import DebugMsg, ErrorMsg, EventMsg


RANK_MAP  = {
            0: "<nothing below>",
            1: "Newbie",
            2: "Script Kiddie",
            3: "Hacker",
            4: "Pro Hacker",
            5: "Elite Hacker",
            6: "Guru",
            7: "Ninja",
            8: "Samurai",
            9: "Sensei",
            10: "Legend",
            11: "Mythic",
            12: "Immortal",
            13: "Godlike",
            14: "<nothing aobve>",
        }

  
class PlayerActivity(Static):

    BATCH_SIZE = 20
    _MORE_KEY = "__more__"

    def get_api(self) -> HTBApiSession:
        return self.app.get_api()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.loading = True
        self.user_data = {"id": None}
        self.activity_data = []
        self._displayed = 0
        self._seen_keys = set()

    def compose(self) -> ComposeResult:
        dt = DataTable(id="player_activity_table")
        dt.show_header = True
        dt.cursor_type = "row"
        dt.add_column(label="Activity")
        dt.add_column(label="Target", width=20)
        dt.add_column(label="Points")
        dt.add_column(label="Date")

        with Container(id="player_activity_container"):
            yield dt

    async def on_mount(self) -> None:
        self.loading = True
        self.run_worker(self._load_activity())

    def _activity_key(self, a):
        return f"{a.get('date','')}__{a.get('id','')}__{a.get('type','')}"

    async def _load_activity(self):
        try:
            await self.app.API.ensure_init()
            uid = self.get_api().CRRENT_USER['info']['id']
            self.user_data["id"] = uid

            data = await self.get_api().async_get(f"/api/v4/profile/activity/{uid}")
            new_activities = data["profile"]["activity"]

            new_count = 0
            for a in new_activities:
                key = self._activity_key(a)
                if key in self._seen_keys:
                    break
                new_count += 1

            if new_count == 0 and self.activity_data:
                return

            self.activity_data = new_activities
            self._seen_keys = {self._activity_key(a) for a in self.activity_data}
            self._displayed = 0

            dt = self.query_one(DataTable)
            dt.clear()
            self._show_batch()

            self.loading = False
            cntr = self.query_one("#player_activity_container")
            cntr.border_title = f"Latest activity for UID:{uid} ({len(self.activity_data)} total)"
        except Exception as e:
            self.post_message(ErrorMsg(e))

    def _show_batch(self):
        dt = self.query_one(DataTable)
        self._remove_sentinel()

        end = min(self._displayed + self.BATCH_SIZE, len(self.activity_data))
        for i in range(self._displayed, end):
            a = self.activity_data[i]
            dt.add_row(
                f"[b]{a['flag_title']}" if "flag_title" in a else f"[b]{a['type']}",
                f"[b]{a['name']}[/b]",
                f"[#9fef00]+{a['points']}pts",
                f"{a['date_diff']}",
            )
        self._displayed = end

        if self._displayed < len(self.activity_data):
            self._add_sentinel()

    def _remove_sentinel(self):
        try:
            self.query_one(DataTable).remove_row(self._MORE_KEY)
        except Exception:
            pass

    def _add_sentinel(self):
        self.query_one(DataTable).add_row(
            "", ".... more ....", "", "", key=self._MORE_KEY)

    def on_data_table_row_highlighted(self, event) -> None:
        if event.row_key and event.row_key.value == self._MORE_KEY:
            self._show_batch()









class PlayerStats(Static):
    """Static widget that shows the player stats."""


    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)        
        self.user_data = {
            "id" : None,
            "name" : None,
            "points" : None,
            "user_owns" : None,
            "system_owns" : None,
            "rank_progress" : None,
            "user_bloods": None,
            "system_bloods": None,
            "respects": None,
        }
        self.current_season = {
            "id" : None,
            "name" : None
        }
        self.season_data = {
            "league": None,
            "rank": None,
            "total_ranks": None,
            "rank_suffix": None,
            "total_season_points": None,
            "flags_to_next_rank": {
                "obtained": None,
                "total": None
            }
        }

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        
        with Container(id="player_stats_container"):
            yield Label(id="player_rank_label")
            yield ProgressBar(id="player_rank_progress", show_percentage=True, show_eta=False, total=100)
            yield Label(id="player_rank_progress_label")
            yield Static(id="player_stats_table")


    async def on_mount(self) -> None:
        """Mount the widget."""
        self.loading = True
        self.run_worker(self.update_profile())

    async def update_profile(self) -> None:
        try:
            await self.app.API.ensure_init()
            table: Table = await self.get_profile()
            await self._append_status(table)
            cntr = self.query_one("#player_stats_container")
            cntr.border_title = f"{self.user_data['name']}::{self.user_data['id']}"
            cntr.styles.border_title_color = "#9fef00"
            self.query_one("#player_rank_label").update("Current level : " + RANK_MAP[self.user_data["rank"]])
            self.query_one("#player_stats_table").update(table)
            self.query_one("#player_rank_progress", ProgressBar).advance(self.user_data["rank_progress"])
            self.query_one("#player_rank_progress_label").update("Progress to : " + RANK_MAP[self.user_data['rank']+1])
            self.loading = False

        except Exception as e:
            self.loading = True
            self.post_message(ErrorMsg(e))

    async def _append_status(self, table):
        table.add_row()
        table.add_row("[b]── Status ──", "")

        machine_text = "None"
        try:
            active = await self.app.get_api().async_get("/api/v4/machine/active", cache_this=0)
            info = active.get("info")
            if info:
                machine_text = f"{info.get('name', '?')} ({info.get('ip', '?')})"
        except Exception:
            pass
        table.add_row("Active Machine", machine_text)

        vpn_text = "Unknown"
        try:
            conn = await self.app.get_api().async_get("/api/v4/connection/status", cache_this=0)
            if conn.get("data"):
                srv = conn["data"].get("server", {})
                vpn_text = srv.get("friendly_name", "Connected")
            else:
                vpn_text = "Disconnected"
        except Exception:
            pass
        table.add_row("VPN", vpn_text)
        table.add_row("Workdir", getattr(self.app, 'WORKDIR', '?'))
            
    def get_user_id(self) -> str:
      
         
        """
        Retrieves the user ID from the API endpoint.

        Returns:
            str: The user ID.
        """
        ses : HTBApiSession = self.app.get_api()
        id = ses.CRRENT_USER['info']['id']
        self.user_data["id"] = id
        return str(id)


    async def get_profile(self):
        """
        Retrieves the profile data for the user.

        Returns:
            dict: The user's profile data.
        """

        ses : HTBApiSession = self.app.get_api()
        self.get_user_id()
        data = await ses.async_get("/api/v4/profile/" + str(self.user_data["id"]))
        
        self.user_data["id"] = data['profile']['id']
        self.user_data["name"] = data['profile']['name']
        self.user_data["rank"] = data['profile']['rank_id']
        self.user_data["ranking"] = data['profile']['ranking']
        self.user_data["points"] = data['profile']['points']
        self.user_data["user_owns"] = data['profile']['user_owns']
        self.user_data["system_owns"] = data['profile']['system_owns']
        self.user_data["rank_progress"] = data['profile']['current_rank_progress']
        self.user_data["user_bloods"] = data['profile']['user_bloods']
        self.user_data["system_bloods"] = data['profile']['system_bloods']
        self.user_data["respects"] = data['profile']['respects']

        await self.get_current_season()
        await self.get_season_data()

        return self.make_profile()
           
        
    async def get_current_season(self):
      
      data = await self.app.get_api().async_get("/api/v4/season/list")
      for season in data["data"]:
          if season["active"] == True:
              self.current_season["id"] = season["id"]
              self.current_season["name"] = season["name"]
              return self.current_season
      #raise Exception("No active season found")      
            
 
    async def get_season_data(self):
        """
        Retrieves the season data for the user.

        """
  
        if self.user_data["id"] is None:
             self.get_user_id()
             
        if self.current_season["id"] is None:
            await self.get_current_season()
            
        if self.current_season["id"] is None:
            return "No active season"
        data = await self.app.get_api().async_get("/api/v4/season/user/rank/" + str(self.current_season["id"]))
        
        # assign data to self.season_data
        self.season_data["league"] = data["data"]["league"]
        self.season_data["rank"] = data["data"]["rank"]
        self.season_data["total_ranks"] = data["data"]["total_ranks"]
        self.season_data["rank_suffix"] = data["data"]["rank_suffix"]
        self.season_data["total_season_points"] = data["data"]["total_season_points"]
        self.season_data["flags_to_next_rank"]["obtained"] = data["data"]["flags_to_next_rank"]["obtained"]
        self.season_data["flags_to_next_rank"]["total"] = data["data"]["flags_to_next_rank"]["total"]

        return self.season_data
 
    
    def make_profile(self):
        #self.log_stuff("PlayerStats.make_profile", user=self.user_data, season=self.season_data) 
        table = Table.grid(
            pad_edge=False,
            expand=True
        )

        table.add_column(ratio=1)
        table.add_column(ratio=1)


        table.add_row(f"Rank: #{self.user_data['ranking']}", f"Points: {self.user_data['points']}") 
        table.add_row()       
        table.add_row(f"User Flag: {self.user_data['user_owns']}", f"System Flag: {self.user_data['system_owns']}")
        table.add_row(f"User Blood: {self.user_data['user_bloods']}", f"System Blood: {self.user_data['system_bloods']}")
        table.add_row()
        table.add_row("Respects", f"{self.user_data['respects']}")
        table.add_row()
        
        # season stats
        table.add_row("Season Tier", str(self.season_data['league'] or '-'))
        table.add_row("Season Rank", f"{self.season_data['rank'] or '-'}/{self.season_data['total_ranks'] or '-'}")
        table.add_row("Season Points", str(self.season_data['total_season_points'] or 0))
        table.add_row("Season Flags", f"{self.season_data['flags_to_next_rank']['obtained'] or 0}/{self.season_data['flags_to_next_rank']['total'] or 0}")
        
        return table
    
    
    
    
    
    
    
    
    
    
    
    
class ContainerPlayerInfo(VerticalScroll):

  def compose(self) -> ComposeResult:
    with Container(id="player_information_container"):
      yield PlayerStats(id="player_stats")
      yield PlayerActivity(id="player_activity")


