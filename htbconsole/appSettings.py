import os
from dataclasses import dataclass, field, asdict
import yaml


_APP_NAME = "htbconsole"
_SETTINGS_BASENAME = "htbSettings.yaml"
YAML_KEY = None


def settings_path():
    """Resolve the settings file location.

    Priority:
      1. ``HTB_SETTINGS`` env var (explicit override)
      2. ``./htbSettings.yaml`` in the current dir, if it already exists (back-compat)
      3. XDG user config: ``$XDG_CONFIG_HOME/htbconsole/htbSettings.yaml``
         (falls back to ``~/.config/htbconsole/``)
    """
    override = os.environ.get("HTB_SETTINGS")
    if override:
        return os.path.expanduser(override)

    cwd_file = os.path.join(os.getcwd(), _SETTINGS_BASENAME)
    if os.path.exists(cwd_file):
        return cwd_file

    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    cfg_dir = os.path.join(base, _APP_NAME)
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, _SETTINGS_BASENAME)

DEFAULT_CUSTOM_ACTIONS = """\
{% if play_info.status == 'ready' %}
{% for port in play_info.ports %}
- [netcat {{play_info.ip}}:{{port}}]({{ cmd('netcat', play_info.ip, port) }})
- [http {{play_info.ip}}:{{port}}](http://{{play_info.ip}}:{{port}}/)
{% endfor %}
{% endif %}
- [Open vsCode here]({{ terminal('code', real_dir_name) }})
- [nmap scan]({{ terminal('nmap', play_info.ip) }})
- [Open terminal]({{ cmd('xfce4-terminal', '-e', 'bash','--working-directory={real_dir_name}') }})
"""

ENV_OVERRIDES = {
    "HTB_WORKDIR": "WORKDIR",
    "USE_BURP":    "burp_proxy",
}


@dataclass
class BaseSettings:
    YAML_KEY: str = field(init=False, repr=False, default="")

    workdir: str = "./WORKDIR"
    zip_password: str = "hackthebox"
    unpack_cmd: str = "7z -o./unpacked/ -p{password} x {file}"
    auto_create_dir: bool = True
    save_logs: bool = True

    @classmethod
    def load(cls):
        s = cls()
        data = _load_yaml().get(s.YAML_KEY, {})
        for k, v in data.items():
            if hasattr(s, k) and v is not None:
                setattr(s, k, v)
        for env_var, attr in ENV_OVERRIDES.items():
            val = os.environ.get(env_var)
            if val and hasattr(s, attr):
                setattr(s, attr, val)
        return s

    def save(self):
        data = _load_yaml()
        d = asdict(self)
        d.pop("YAML_KEY", None)
        data[self.YAML_KEY] = d
        _save_yaml(data)

    def to_dict(self):
        d = asdict(self)
        d.pop("YAML_KEY", None)
        return d


@dataclass
class HTBSettings(BaseSettings):
    YAML_KEY: str = field(init=False, repr=False, default="htb")

    terminal: str = "/usr/bin/xfce4-terminal --hold -x "
    use_cache: bool = False
    custom_actions: str = field(default_factory=lambda: DEFAULT_CUSTOM_ACTIONS)
    burp_proxy: str = ""


@dataclass
class CTFSettings(BaseSettings):
    YAML_KEY: str = field(init=False, repr=False, default="ctf")


def _load_yaml():
    path = settings_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(data):
    with open(settings_path(), "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
