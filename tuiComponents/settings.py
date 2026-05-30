from textual import on
from textual.widgets import Static, Button, Label, Switch, Input
from textual.containers import Container, VerticalScroll, Horizontal
from textual.app import ComposeResult

from rich.table import Table

from .messages import DebugMsg, EventMsg, ErrorMsg


class ContainerSettings(VerticalScroll):

    def compose(self) -> ComposeResult:
        with Container(id="settings_main"):
            with Container(id="settings_api"):
                yield Label("[b]API Settings", id="settings_api_title")
                yield Static(id="settings_api_info")
                with Horizontal(id="settings_cache_row"):
                    yield Label("Enable request cache")
                    yield Switch(id="settings_cache_toggle", value=False)
                with Horizontal(id="settings_burp_row"):
                    yield Label("Burp proxy (127.0.0.1:8080)")
                    yield Switch(id="settings_burp_toggle", value=False)
                yield Button("Clear cache", id="settings_clear_cache_button")
                yield Button("Refresh all data", id="settings_refresh_button", variant="primary")

            with Container(id="settings_workdir"):
                yield Label("[b]Work Directory", id="settings_workdir_title")
                yield Input(value="", placeholder="./work", id="settings_workdir_input")

            with Container(id="settings_extract"):
                yield Label("[b]Extraction", id="settings_extract_title")
                yield Input(value="", placeholder="hackthebox", id="settings_zip_password_input", password=True)
                yield Label("Unpack command ({password}, {file}, {dir}):")
                yield Input(value="", placeholder="7z -o./unpacked/ -p{password} x {file}", id="settings_unpack_cmd_input")

            with Container(id="settings_terminal"):
                yield Label("[b]Terminal Emulator", id="settings_terminal_title")
                yield Input(value="", placeholder="/usr/bin/xfce4-terminal --hold -x ", id="settings_terminal_input")

            with Container(id="settings_vpn"):
                yield Label("[b]VPN / Connection", id="settings_vpn_title")
                yield Static(id="settings_vpn_info")
                yield Button("Refresh VPN status", id="settings_vpn_refresh_button")

    async def on_mount(self):
        self.run_worker(self._load_settings())

    async def _load_settings(self):
        try:
            await self.app.API.ensure_init()
            api = self.app.API

            self.query_one("#settings_cache_toggle", Switch).value = bool(api.USE_CACHE)

            import os
            self.query_one("#settings_burp_toggle", Switch).value = bool(os.environ.get("USE_BURP"))

            self.query_one("#settings_workdir_input", Input).value = self.app.WORKDIR
            self.query_one("#settings_zip_password_input", Input).value = self.app.ZIP_PASSWORD
            self.query_one("#settings_unpack_cmd_input", Input).value = self.app.UNPACK_CMD
            self.query_one("#settings_terminal_input", Input).value = self.app.TERMINAL

            self._refresh_api_info()
            await self._refresh_vpn_info()
        except Exception as e:
            self.post_message(ErrorMsg(e))

    def _refresh_api_info(self):
        api = self.app.API
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(ratio=2)

        user = api.CRRENT_USER.get("info", {})
        token = api.APITOKEN
        masked = token[:10] + "..." + token[-6:] if len(token) > 20 else "***"

        table.add_row("Base URL", api.base_url)
        table.add_row("Token", masked)
        table.add_row("User", f"{user.get('name', '?')} (ID: {user.get('id', '?')})")
        table.add_row("Cache entries", str(len(api.CACHE)))
        table.add_row("Cache enabled", "Yes" if api.USE_CACHE else "No")

        cats = api.CHALLENGE_CATEGORIES
        if cats:
            table.add_row("Categories", str(len(cats.name_to_id)))

        self.query_one("#settings_api_info").update(table)

    async def _refresh_vpn_info(self):
        try:
            data = await self.app.API.async_get("/api/v4/connections/servers", cache_this=0)
            table = Table.grid(expand=True)
            table.add_column(ratio=1)
            table.add_column(ratio=2)

            servers = data.get("data", [])
            if servers:
                for srv in servers[:5]:
                    name = srv.get("friendly_name", srv.get("hostname", "?"))
                    loc = srv.get("location", "?")
                    table.add_row(name, loc)
            else:
                table.add_row("Status", "No VPN servers loaded")

            self.query_one("#settings_vpn_info").update(table)
        except Exception:
            self.query_one("#settings_vpn_info").update("Could not load VPN info")

    @on(Switch.Changed, "#settings_cache_toggle")
    def toggle_cache(self, event: Switch.Changed):
        self.app.API.USE_CACHE = 1 if event.value else 0
        self.app.post_message(EventMsg(f"Cache {'enabled' if event.value else 'disabled'}"))
        self._refresh_api_info()

    @on(Switch.Changed, "#settings_burp_toggle")
    async def toggle_burp(self, event: Switch.Changed):
        import os
        import httpApi
        if event.value:
            os.environ["USE_BURP"] = "1"
            import httpx
            httpApi.burp_proxy = httpx.Proxy("http://127.0.0.1:8080")
        else:
            os.environ.pop("USE_BURP", None)
            httpApi.burp_proxy = None
        await self.app.API.close()
        self.app.post_message(EventMsg(f"Burp proxy {'enabled' if event.value else 'disabled'}"))

    @on(Button.Pressed, "#settings_clear_cache_button")
    def clear_cache(self, event):
        self.app.API.CACHE = {}
        import json
        json.dump({}, open(self.app.API._CACHE_FILE, "w"))
        self.app.post_message(EventMsg("Cache cleared"))
        self._refresh_api_info()

    @on(Button.Pressed, "#settings_refresh_button")
    async def refresh_all(self, event):
        self.app.post_message(EventMsg("Refreshing all data..."))
        self.app.API._initialized = False
        await self.app.API.ensure_init()
        self._refresh_api_info()
        self.app.post_message(EventMsg("Data refreshed"))

    @on(Input.Submitted, "#settings_zip_password_input")
    def update_zip_password(self, event: Input.Submitted):
        self.app.ZIP_PASSWORD = event.value
        self.app.post_message(EventMsg("Zip password updated"))

    @on(Input.Submitted, "#settings_unpack_cmd_input")
    def update_unpack_cmd(self, event: Input.Submitted):
        val = event.value.strip()
        if val:
            self.app.UNPACK_CMD = val
            self.app.post_message(EventMsg(f"Unpack command set to: {val}"))

    @on(Input.Submitted, "#settings_workdir_input")
    def update_workdir(self, event: Input.Submitted):
        import os
        val = event.value.strip()
        if val:
            self.app.WORKDIR = val
            os.makedirs(val, exist_ok=True)
            self.app.API._CACHE_FILE = os.path.join(val, "req_cache.json")
            self.app.post_message(EventMsg(f"Workdir set to: {os.path.abspath(val)}"))

    @on(Input.Submitted, "#settings_terminal_input")
    def update_terminal(self, event: Input.Submitted):
        val = event.value.strip()
        if val:
            self.app.TERMINAL = val
            self.app.post_message(EventMsg(f"Terminal set to: {val}"))

    @on(Button.Pressed, "#settings_vpn_refresh_button")
    async def refresh_vpn(self, event):
        await self._refresh_vpn_info()
