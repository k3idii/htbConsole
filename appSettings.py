import os
from dataclasses import dataclass, field, asdict
import yaml


SETTINGS_FILE = "./htbSettings.yaml"
YAML_KEY = None

DEFAULT_CUSTOM_ACTIONS = """\
{% if play_info.status == 'ready' %}
{% for port in play_info.ports %}
- [netcat {{play_info.ip}}:{{port}}]({{ cmd('netcat', play_info.ip, port) }})
- [http {{play_info.ip}}:{{port}}](http://{{play_info.ip}}:{{port}}/)
{% endfor %}
{% endif %}
- [Open vsCode here]({{ cmd('code', real_dir_name) }})
- [nmap scan]({{ cmd('nmap', play_info.ip) }})
- [Open terminal]({{ cmd('xfce4-terminal', '-e', 'bash','--working-directory={real_dir_name}') }})
"""

ENV_OVERRIDES = {
    "HTB_WORKDIR": "workdir",
    "USE_BURP":    "burp_proxy",
}


@dataclass
class BaseSettings:
    YAML_KEY: str = field(init=False, repr=False, default="")

    workdir: str = "./work"
    zip_password: str = "hackthebox"
    unpack_cmd: str = "7z -o./unpacked/ -p{password} x {file}"
    auto_create_dir: bool = True

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
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(data):
    with open(SETTINGS_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
