import os

from textual.widgets import TextArea

from .messages import EventMsg


class NotesEditor(TextArea):

  language = "markdown"
  FILE: str = None

  BINDINGS = [("ctrl+s", "save_file")]

  def action_save_file(self):
    if self.FILE is None:
      return
    os.makedirs(os.path.dirname(self.FILE), exist_ok=True)
    with open(self.FILE, "w") as f:
      f.write(self.text)
    self.app.post_message(EventMsg(f"SAVED {self.FILE}"))

  def set_filepath(self, fp):
    if self.FILE is not None:
      self.action_save_file()
    self.FILE = fp
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    if not os.path.exists(fp):
      with open(fp, "w") as f:
        f.write("")
      self.app.post_message(EventMsg(f"Create notes: {self.FILE}"))
    with open(self.FILE, "r") as f:
      self.text = f.read()
    self.app.post_message(EventMsg(f"Loaded notes from {self.FILE}"))

  def on_unmount(self):
    self.action_save_file()
