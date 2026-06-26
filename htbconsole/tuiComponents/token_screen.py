from textual.screen import ModalScreen
from textual.widgets import Label, Button, Input
from textual.containers import Container, Horizontal
from textual.app import ComposeResult


class TokenInputScreen(ModalScreen):

    CSS = """
    TokenInputScreen { align: center middle; }
    #token_dialog {
        width: 70%;
        height: auto;
        padding: 2;
        background: #1a2332;
        border: panel #3d5276;
    }
    #token_dialog Label { width: 100%; margin-bottom: 1; }
    #token_dialog Input { width: 100%; margin-bottom: 1; }
    #token_buttons { layout: horizontal; width: 100%; }
    #token_buttons Button { width: 1fr; }
    """

    def __init__(self, title="API Token Required", message="", token_env="HTB_TOKEN"):
        super().__init__()
        self._title = title
        self._message = message
        self._token_env = token_env

    def compose(self) -> ComposeResult:
        with Container(id="token_dialog"):
            yield Label(f"[b]{self._title}[/b]")
            if self._message:
                yield Label(self._message)
            yield Label(f"Paste your token ({self._token_env}):")
            yield Input(placeholder="eyJ0eXAi...", id="token_input", password=True)
            with Horizontal(id="token_buttons"):
                yield Button("OK", id="token_ok", variant="success")
                yield Button("Cancel (quit)", id="token_cancel")

    def on_button_pressed(self, event):
        if event.button.id == "token_ok":
            val = self.query_one("#token_input", Input).value.strip()
            self.dismiss(val if val else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event):
        val = event.value.strip()
        self.dismiss(val if val else None)
