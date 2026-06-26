from textual.message import Message
import rich.pretty
import traceback

class SelfFormattingMsg(Message):
    COLOR = "silver"
    arg = None
 
    def __init__(self, arg, *a, **kw):
        super().__init__()
        self.arg = arg
        self.create(*a,**kw)
        
    def create(self):
        ...
    
    def get_content(self):
        return [ self.arg ]
        
    def __rich__(self) -> str:
        parts = [  f"[bold {self.COLOR}] {self.__class__.__name__} [/bold {self.COLOR}]" ]
        parts += self.get_content()
        return ' | '.join(parts)
            
 
class ErrorMsg(SelfFormattingMsg):
    COLOR="red"
    def get_content(self):
        r = [ rich.pretty.pretty_repr(self.arg) ]
        fmt = traceback.format_exception(self.arg)
        r += fmt
        return r

class EventMsg(SelfFormattingMsg):
    COLOR="blue"
    pass 

class DebugMsg(SelfFormattingMsg):
    def create(self, *a, **kw):
        self._a = a
        self._kw = kw
    
    def get_content(self):
        val = [self.arg]
        if self._a:
            val.append(rich.pretty.pretty_repr( self._a ))
        if self._kw:
            val.append(rich.pretty.pretty_repr(self._kw ))
        return val





 