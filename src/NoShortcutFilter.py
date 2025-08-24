from PyQt6.QtCore import Qt, QObject, QEvent


class NoShortcutFilter(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress:
            key = ev.key()
            mods = ev.modifiers()

            # Allow Ctrl+W to propagate normally
            if (mods & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_W:
                return False  # don't swallow → normal processing

            # Block everything else
            ev.ignore()
            return True
        return super().eventFilter(obj, ev)
