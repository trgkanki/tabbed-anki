from aqt import mw, dialogs
from aqt.utils import tooltip
from anki.utils import is_mac

from .utils import debugLog  # debug log registered here

from typing import Optional, Dict, cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QMdiArea,
    QMdiSubWindow,
)

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence


class TabbedMainWindow(QMainWindow):
    @staticmethod
    def _makeWindowInner(window: QMainWindow):
        """Make MainWindow convertible to tabs.

        Note: This must be called BEFORE window is "shown" (e.g geometry is queried)
        or it will sefgault.

        ChatGPT says:
        This crash is a known foot-gun: on macOS you generally cannot “demote” a
        live top-level QMainWindow into a child widget by wtoggling off Qt.Window
        and dropping it into a layout. Cocoa’s NSWindow/toolbar/menubar wiring is
        already created; changing window flags + reparenting after that can corrupt
        the native window stack → segfault.
        """
        if is_mac:
            menuBar = window.menuBar()
            if menuBar:
                menuBar.setNativeMenuBar(False)

    def __init__(self, mw):
        super().__init__()

        self.mw = mw

        # Demote this window before anything happens
        TabbedMainWindow._makeWindowInner(mw)

        self.setWindowTitle(mw.windowTitle())
        self.resize(mw.size())
        self.setWindowIcon(mw.windowIcon())

        # intercept other messages
        mw.show = lambda: self.show()
        mw.hide = lambda: self.hide()
        oldSetTitle = mw.setWindowTitle

        def newSetTitle(a0: Optional[str]):
            self.setWindowTitle(a0)
            oldSetTitle(a0)

        mw.setWindowTitle = newSetTitle

        self._windowMap: Dict[str, QMainWindow] = {}

        # Tab widget becomes the central area, tabs on top by default
        self._mru = []
        mdi = QMdiArea()
        self.mdi = mdi

        mdi.setViewMode(QMdiArea.ViewMode.TabbedView)
        mdi.setTabsClosable(True)
        mdi.setTabsMovable(True)
        mdi.setTabShape(QTabWidget.TabShape.Rounded)
        mdi.setDocumentMode(True)
        self.setCentralWidget(mdi)

        mdi.subWindowActivated.connect(self._onTabChange)

        shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(self._closeCurrentTab)
        # TODO: there should be better way to handle activatedAmbiguously.
        shortcut.activatedAmbiguously.connect(self._closeCurrentTab)

        # Create and add inner windows as tab pages
        self.addAndShowInnerWindow("AnkiQt", mw)

        # mark..
        oldMarkClosed = dialogs.markClosed

        def newMarkClosed(name: str):
            debugLog.log("newMarkClosed %s" % (name,))
            oldMarkClosed(name)
            try:
                window = self._windowMap[name]
            except KeyError:
                return
            debugLog.log(" - removing window %s" % (window,))
            self._onMarkClosed(window)

        dialogs.markClosed = newMarkClosed

        # (Optional) programmatic navigation example:
        # tabs.setCurrentIndex(1)  # select "InnerWindow2" on startup

    def _findSubwindowContainingWindow(
        self, window: QMainWindow
    ) -> Optional[QMdiSubWindow]:
        windows = self.mdi.subWindowList()
        for w in windows:
            if w.widget() == window:
                return w
        return None

    def addAndShowInnerWindow(self, clsName: str, window: QMainWindow):
        subWindow = self._findSubwindowContainingWindow(window)
        if subWindow:
            self.mdi.setActiveSubWindow(subWindow)
        else:
            TabbedMainWindow._makeWindowInner(window)
            subWindow = self.mdi.addSubWindow(window)
            debugLog.log("Added subwindow %s for %s" % (subWindow, window))

            window.activateWindow = lambda: self._activateSubwindow(window)
            window.raise_ = lambda: self._raiseSubwindow(window)

            self._windowMap[clsName] = window
            self.mdi.setActiveSubWindow(subWindow)

    def selectTabIfExists(self, clsName: str):
        try:
            window = self._windowMap[clsName]
        except KeyError:
            return

        subWindow = self._findSubwindowContainingWindow(window)
        if subWindow:
            self.mdi.setActiveSubWindow(subWindow)

    def _closeCurrentTab(self):
        subWindow = self.mdi.currentSubWindow()
        if not subWindow:
            return
        widget = subWindow.widget()
        if widget:
            if widget == self.mw:
                # Main widget cannot be closed with Ctrl+W
                tooltip("Main window should be closed by Alt+F4 / Cmd+Q")
                return
            widget.close()

    def _onTabChange(self, subWindow):
        if subWindow:
            widget = subWindow.widget()
            try:
                self._mru.remove(widget)
            except ValueError:
                pass
            self._mru.insert(0, widget)
            # debugLog.log("tab changed to %d (%s), mru %s" % (idx, widget, self._mru))

    def _activateSubwindow(self, window: QMainWindow):
        subWindow = self._findSubwindowContainingWindow(window)
        if not subWindow:
            return
        self.mdi.setActiveSubWindow(subWindow)

    def _raiseSubwindow(self, window: QMainWindow):
        subWindow = self._findSubwindowContainingWindow(window)
        if subWindow:
            self.mdi.setActiveSubWindow(subWindow)
            self.raise_()

    def _onMarkClosed(self, w):
        try:
            self._mru.remove(w)
        except ValueError:
            pass

        for candidate in self._mru:
            # debugLog.log(" - testing candidate %s" % w)
            candidateSubWindow = self._findSubwindowContainingWindow(candidate)
            if candidateSubWindow:
                self.mdi.setActiveSubWindow(candidateSubWindow)
                break

        subWindow = self._findSubwindowContainingWindow(w)
        if subWindow:
            self.mdi.removeSubWindow(subWindow)
            # close() will be handled on each window code.
            # markClosed is just a marker that the window is closed.

    def closeEvent(self, a0):
        event = a0
        self.mw.close()
        if event:
            event.ignore()

    # This is THE hacky code of this program...
    # Anki compares current focused window (`app.focusWidget().window()`) to
    # a lot of windows to check if each window is focused. To do that it
    # compares window like:
    #
    #  self.mw.app.focusWidget().window() != self.mw
    #
    # LHS of this expression is expected to be `TabbedMainWindow`, but rhs might
    # be `mw`, `AddCards` instance, or `Browser` instance or so on. So this
    # equality will ALWAYS break. To circumvent this we just assume that the
    # equality holds IF the current focused window TabbedMainWindow equals to
    # the RHS.
    #
    # This fixes a lot of compatibility problems, like main window not accepting
    # focus even if the tab is focused. (Reviewer, DeckBrowser, etc)
    def __eq__(self, other):
        # Identity fast-path
        if other is self:
            return True
        # Treat canonical mainwindow as equal

        active = self.mdi.activeSubWindow()
        if active and active.widget() is other:
            return True

        # For anything else, defer to the other side
        return NotImplemented

    # I doubt `__ne__` is ever implemented on super class QMainWindow, but here
    # I wanna regard QMainWindow as builtin types. As we're overriding `__eq__`
    # of builtins we override `__ne__` too.
    # https://stackoverflow.com/questions/4352244/should-ne-be-implemented-as-the-negation-of-eq
    def __ne__(self, other):
        return not self == other


newMainWindow = TabbedMainWindow(mw)
