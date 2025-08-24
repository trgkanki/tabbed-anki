from PyQt6.QtCore import Qt, QObject, QEvent
from PyQt6.QtGui import QKeyEvent
from typing import cast


class NoShortcutFilter(QObject):
    def eventFilter(self, a0, a1):
        obj = a0
        ev = a1

        if ev and ev.type() == QEvent.Type.KeyPress:
            ev = cast(QKeyEvent, ev)
            key = ev.key()
            mods = ev.modifiers()

            # Allow Ctrl+W to propagate normally
            if (mods & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_W:
                return False  # don't swallow → normal processing

            # Block everything else
            ev.ignore()
            return True
        return super().eventFilter(obj, ev)
