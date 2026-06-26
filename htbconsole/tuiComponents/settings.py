from textual import on
from textual.widgets import Static, Button, Label, Switch, Input, TextArea
from textual.containers import Container, VerticalScroll, Horizontal
from textual.app import ComposeResult

from rich.table import Table

from .messages import DebugMsg, EventMsg, ErrorMsg
from ..appSettings import DEFAULT_CUSTOM_ACTIONS


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
                    yield Label("Burp proxy")
                    yield Input(placeholder="http://127.0.0.1:8080", id="settings_burp_input")
                    yield Switch(id="settings_burp_toggle", value=False)
                yield Button("Clear cache", id="settings_clear_cache_button")
                yield Button("Refresh all data", id="settings_refresh_button", variant="primary")

            with Container(id="settings_workdir"):
                yield Label("[b]Work Directory", id="settings_workdir_title")
                yield Input(value="", placeholder="./work", id="settings_workdir_input")
                with Horizontal(id="settings_autocreate_row"):
                    yield Label("Auto-create task directories")
                    yield Switch(id="settings_autocreate_toggle", value=True)

            with Container(id="settings_extract"):
                yield Label("[b]Extraction", id="settings_extract_title")
                yield Input(value="", placeholder="hackthebox", id="settings_zip_password_input", password=True)
                yield Label("Unpack command ({password}, {file}, {dir}):")
                yield Input(value="", placeholder="7z -o./unpacked/ -p{password} x {file}", id="settings_unpack_cmd_input")

            with Container(id="settings_terminal"):
                yield Label("[b]Terminal Emulator", id="settings_terminal_title")
                yield Input(value="", placeholder="/usr/bin/xfce4-terminal --hold -x ", id="settings_terminal_input")

            with Container(id="settings_actions"):
                yield Label("[b]Custom Actions (Challenges)", id="settings_actions_title")
                yield Label(
                    "Jinja2 template. Use cmd(arg, ...) to build exec() links (no terminal will popup!)"
                    "EXAMPLE: {{ cmd('echo','1') }}\n\n"
                    "Use terminal(arg, ...) to open command in a new terminal:\n "
                    "EXAMPLE: {{ terminal('nmap', play_info.ip) }}\n"
                    ,
                    id="settings_actions_help",
                )
                yield Label(
                    "Variables: name, difficulty, play_info.ip, play_info.ports, "
                    "play_info.status, real_dir_name, local_dir_name, category_name",
                    id="settings_actions_vars",
                )
                yield TextArea("", language="markdown", id="settings_actions_editor")
                with Horizontal(id="settings_actions_buttons"):
                    yield Button("Apply", id="settings_actions_apply_button", variant="primary")
                    yield Button("Reset to default", id="settings_actions_reset_button")

            with Container(id="settings_vpn"):
                yield Label("[b]VPN / Connection", id="settings_vpn_title")
                yield Static(id="settings_vpn_info")
                yield Button("Refresh VPN status", id="settings_vpn_refresh_button")

    async def on_mount(self):
        self.run_worker(self._load_settings())

    async def _load_settings(self):
        try:
            await self.app.API.ensure_init()
            s = self.app.settings

            self.query_one("#settings_cache_toggle", Switch).value = s.use_cache
            self.query_one("#settings_burp_input", Input).value = s.burp_proxy
            self.query_one("#settings_burp_toggle", Switch).value = bool(s.burp_proxy)
            self.query_one("#settings_workdir_input", Input).value = s.workdir
            self.query_one("#settings_autocreate_toggle", Switch).value = s.auto_create_dir
            self.query_one("#settings_zip_password_input", Input).value = s.zip_password
            self.query_one("#settings_unpack_cmd_input", Input).value = s.unpack_cmd
            self.query_one("#settings_terminal_input", Input).value = s.terminal
            self.query_one("#settings_actions_editor", TextArea).text = s.custom_actions or ''

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
        table.add_row("Cache enabled", "Yes" if self.app.settings.use_cache else "No")

        cats = getattr(self.app, '_challenge_categories', None)
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

    def _persist(self):
        self.app.settings.save()

    @on(Switch.Changed, "#settings_cache_toggle")
    def toggle_cache(self, event: Switch.Changed):
        self.app.settings.use_cache = event.value
        self.app.API.USE_CACHE = 1 if event.value else 0
        self.app.post_message(EventMsg(f"Cache {'enabled' if event.value else 'disabled'}"))
        self._refresh_api_info()
        self._persist()

    @on(Switch.Changed, "#settings_burp_toggle")
    async def toggle_burp(self, event: Switch.Changed):
        import os
        import httpx
        from .. import httpApi
        addr = self.query_one("#settings_burp_input", Input).value.strip()
        if event.value and addr:
            self.app.settings.burp_proxy = addr
            os.environ["USE_BURP"] = addr
            httpApi.burp_proxy = httpx.Proxy(addr)
        else:
            self.app.settings.burp_proxy = ""
            os.environ.pop("USE_BURP", None)
            httpApi.burp_proxy = None
            if event.value and not addr:
                self.app.notify("Enter proxy address first", severity="warning")
                self.query_one("#settings_burp_toggle", Switch).value = False
                return
        await self.app.API.close()
        self.app.post_message(EventMsg(f"Burp proxy {'enabled: ' + addr if event.value else 'disabled'}"))
        self._persist()

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

    @on(Switch.Changed, "#settings_autocreate_toggle")
    def toggle_autocreate(self, event: Switch.Changed):
        self.app.settings.auto_create_dir = event.value
        self.app.post_message(EventMsg(f"Auto-create directories {'enabled' if event.value else 'disabled'}"))
        self._persist()

    @on(Input.Submitted, "#settings_zip_password_input")
    def update_zip_password(self, event: Input.Submitted):
        self.app.settings.zip_password = event.value
        self.app.post_message(EventMsg("Zip password updated"))
        self._persist()

    @on(Input.Submitted, "#settings_unpack_cmd_input")
    def update_unpack_cmd(self, event: Input.Submitted):
        val = event.value.strip()
        if val:
            self.app.settings.unpack_cmd = val
            self.app.post_message(EventMsg(f"Unpack command set to: {val}"))
            self._persist()

    @on(Input.Submitted, "#settings_workdir_input")
    def update_workdir(self, event: Input.Submitted):
        import os
        val = event.value.strip()
        if val:
            self.app.settings.workdir = val
            os.makedirs(val, exist_ok=True)
            self.app.API._CACHE_FILE = os.path.join(val, "req_cache.json")
            self.app.post_message(EventMsg(f"Workdir set to: {os.path.abspath(val)}"))
            self._persist()

    @on(Input.Submitted, "#settings_terminal_input")
    def update_terminal(self, event: Input.Submitted):
        val = event.value.strip()
        if val:
            self.app.settings.terminal = val
            self.app.post_message(EventMsg(f"Terminal set to: {val}"))
            self._persist()

    @on(Button.Pressed, "#settings_actions_apply_button")
    def apply_actions(self, event):
        from .challs import render_custom_actions, MOCK_TASK_CONTEXT
        src = self.query_one("#settings_actions_editor", TextArea).text
        try:
            render_custom_actions(src, MOCK_TASK_CONTEXT)
        except Exception as e:
            self.app.notify(f"Template error: {e}", severity="error")
            return
        self.app.settings.custom_actions = src
        self.app.post_message(EventMsg("Custom actions updated"))
        self.app.notify("Custom actions applied", timeout=3)
        self._persist()

    @on(Button.Pressed, "#settings_actions_reset_button")
    def reset_actions(self, event):
        self.app.settings.custom_actions = DEFAULT_CUSTOM_ACTIONS
        self.query_one("#settings_actions_editor", TextArea).text = DEFAULT_CUSTOM_ACTIONS
        self.app.post_message(EventMsg("Custom actions reset to default"))
        self.app.notify("Custom actions reset", timeout=3)
        self._persist()

    @on(Button.Pressed, "#settings_vpn_refresh_button")
    async def refresh_vpn(self, event):
        await self._refresh_vpn_info()
