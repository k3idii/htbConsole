import os

from textual.screen import ModalScreen
from textual.widgets import Label, Button
from textual.containers import Container, Horizontal
from textual.app import ComposeResult


class ConfirmCreateDirScreen(ModalScreen):

    CSS = """
    ConfirmCreateDirScreen { align: center middle; }
    #confirm_dir_dialog { width: 60%; height: auto; padding: 2; background: #1a2332; border: panel #3d5276; }
    #confirm_dir_dialog Label { width: 100%; margin-bottom: 1; }
    #confirm_dir_buttons { layout: horizontal; width: 100%; }
    #confirm_dir_buttons Button { width: 1fr; }
    """

    def __init__(self, path):
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        with Container(id="confirm_dir_dialog"):
            yield Label("[b]Create directory?[/b]")
            yield Label(f"{self._path}")
            with Horizontal(id="confirm_dir_buttons"):
                yield Button("Create", id="confirm_dir_yes", variant="success")
                yield Button("Skip", id="confirm_dir_no")

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "confirm_dir_yes")


def ensure_task_dir(app, path, callback):
    """Ensure a task directory exists.

    If AUTO_CREATE_DIR is True, creates it silently.
    If False, shows a confirmation modal; callback(path) is called
    only after the directory exists (created by user choice or already present).
    callback(None) is called if the user declines.
    """
    if os.path.isdir(path):
        callback(path)
        return

    if getattr(getattr(app, 'settings', None), 'auto_create_dir', True):
        os.makedirs(path, exist_ok=True)
        callback(path)
        return

    def _on_confirm(confirmed):
        if confirmed:
            os.makedirs(path, exist_ok=True)
            callback(path)
        else:
            callback(None)

    app.push_screen(ConfirmCreateDirScreen(path), _on_confirm)
