from . import TabbedMainWindow
from aqt.addcards import AddCards
from anki.hooks import wrap


# Add cards 'quit without saving' confirmation
def cb(self, onOk):
    try:
        if not self.editor.fieldsAreBlank(self._last_added_note):
            TabbedMainWindow.newMainWindow.selectTabIfExists("AddCards")
    except AttributeError:
        pass


AddCards.ifCanClose = wrap(AddCards.ifCanClose, cb, "before")
