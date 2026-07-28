from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import DataTable, Static, Markdown

from ..httpApi import HTBApiSession
from .messages import DebugMsg, ErrorMsg, EventMsg


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
            14: "<nothing above>",
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
        return f"{a.get('id','')}__{a.get('type','')}"

    async def _load_activity(self):
        try:
            await self.app.ensure_init()
            if not self.app.CURRENT_USER:
                return
            uid = self.app.CURRENT_USER['info']['id']
            self.user_data["id"] = uid

            data = await self.get_api().api_htb_profile_activity(uid)
            new_activities = data['data']

            new_count = 0
            for a in new_activities:
                key = self._activity_key(a)
                if key in self._seen_keys:
                    break
                new_count += 1

            if new_count == 0 and self.activity_data:
                return

            self.app.notify(f"Found {new_count} new activities")

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
            if a['type'] == 'challenge':
                # use name + categoryName:
                name = f"{a['name']}/{a['categoryName']}"
            else:
                name = a['name']
            
            dt.add_row(
                f"[b]{a['type']}[/b]",
                f"[b]{name}[/b]",
                f"[#9fef00]+{a['points']}pts",
                f"{a['ownDate']}",
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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user_data = {}
        self.current_season = {"id": None, "name": None}
        self.season_data = {
            "league": None, "rank": None, "total_ranks": None,
            "rank_suffix": None, "total_season_points": None,
            "flags_to_next_rank": {"obtained": None, "total": None},
        }

    def compose(self) -> ComposeResult:
        with Container(id="player_stats_container"):
            yield Markdown("*Loading...*", id="player_stats_md")

    async def on_mount(self) -> None:
        self.loading = True
        self.run_worker(self.update_profile())

    async def update_profile(self) -> None:
        try:
            await self.app.ensure_init()
            await self._fetch_profile()
            await self._fetch_season()
            status = await self._fetch_status()
            md = self._render_markdown(status)
            cntr = self.query_one("#player_stats_container")
            cntr.border_title = f"{self.user_data.get('name', '?')}::{self.user_data.get('id', '?')}"
            cntr.styles.border_title_color = "#9fef00"
            self.query_one("#player_stats_md", Markdown).update(md)
            self.loading = False
        except Exception as e:
            self.post_message(ErrorMsg(e))

    async def _fetch_profile(self):
        await self.app.ensure_init()
        if not self.app.CURRENT_USER:
            return
        ses = self.app.get_api()
        uid = self.app.CURRENT_USER['info']['id']
        data = await ses.api_htb_profile(uid)
        p = data['profile']
        self.user_data = {
            "id": p['id'], "name": p['name'], "rank": p['rank_id'],
            "ranking": p['ranking'], "points": p['points'],
            "user_owns": p['user_owns'], "system_owns": p['system_owns'],
            "rank_progress": p['current_rank_progress'],
            "user_bloods": p['user_bloods'], "system_bloods": p['system_bloods'],
            "respects": p['respects'],
        }

    async def _fetch_season(self):
        data = await self.app.get_api().api_htb_season_list()
        for season in data.get("data", []):
            if season.get("active"):
                self.current_season = {"id": season["id"], "name": season["name"]}
                break

        if self.current_season["id"] is None:
            return
        data = await self.app.get_api().api_htb_season_user_rank(self.current_season['id'])
        d = data.get("data", {})
        self.season_data["league"] = d.get("league")
        self.season_data["rank"] = d.get("rank")
        self.season_data["total_ranks"] = d.get("total_ranks")
        self.season_data["rank_suffix"] = d.get("rank_suffix")
        self.season_data["total_season_points"] = d.get("total_season_points")
        ftnr = d.get("flags_to_next_rank", {})
        self.season_data["flags_to_next_rank"]["obtained"] = ftnr.get("obtained")
        self.season_data["flags_to_next_rank"]["total"] = ftnr.get("total")

    async def _fetch_status(self):
        status = {"machine": "None", "vpn": "Unknown", "workdir": self.app.settings.workdir}
        try:
            active = await self.app.get_api().api_htb_machine_active(cache_this=0)
            info = active.get("info")
            if info:
                status["machine"] = f"{info.get('name', '?')} ({info.get('ip', '?')})"
        except Exception:
            pass
        try:
            conn = await self.app.get_api().api_htb_connection_status(cache_this=0)
            if conn:
                lines = []
                for c in conn:
                    srv = c.get('server', {}).get('friendly_name', '?')
                    cn = c.get('connection', {})
                    lines.append(f"{c.get('type', '?')}/{srv} — {cn.get('name', '?')} `{cn.get('ip4', '?')}`")
                status["vpn"] = " | ".join(lines)
            else:
                status["vpn"] = "Disconnected"
        except Exception:
            pass
        return status

    def _progress_bar(self, pct):
        filled = int(pct / 5)
        empty = 20 - filled
        return f"`{'█' * filled}{'░' * empty}` {pct}%"

    def _render_markdown(self, status):
        u = self.user_data
        s = self.season_data
        rank_name = RANK_MAP.get(u.get('rank', 0), '?')
        next_rank = RANK_MAP.get(u.get('rank', 0) + 1, '?')
        progress = u.get('rank_progress', 0)

        lines = [
            f"### {rank_name}",
            f"{self._progress_bar(progress)} → *{next_rank}*",
            "",
            f"**Rank** : #{u.get('ranking', '?')}  ",
            f"**Points** : {u.get('points', 0)}  ",
            f"**User Flags** : {u.get('user_owns', 0)}  ",
            f"**System Flags** : {u.get('system_owns', 0)}  ",
            f"**User Bloods** : {u.get('user_bloods', 0)}  ",
            f"**System Bloods** : {u.get('system_bloods', 0)}  ",
            f"**Respects** : {u.get('respects', 0)}  ",
            "",
            f"**Season** — {s.get('league') or '-'} \n"
            f"Rank {s.get('rank') or '-'}/{s.get('total_ranks') or '-'} \n"
            f"{s.get('total_season_points') or 0} pts · "
            f"Flags {s['flags_to_next_rank'].get('obtained') or 0}/{s['flags_to_next_rank'].get('total') or 0}",
            "",
            "---",
            f"- **Active Machine** — {status['machine']}",
            f"- **VPN** — {status['vpn']}",
            f"- **Workdir** — `{status['workdir']}`",
        ]
        return "\n".join(lines)
    
    
    
    
    
    
    
    
    
    
    
    
class ContainerPlayerInfo(VerticalScroll):

  def compose(self) -> ComposeResult:
    with Container(id="player_information_container"):
      yield PlayerStats(id="player_stats")
      yield PlayerActivity(id="player_activity")


