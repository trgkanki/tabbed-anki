from aqt import mw, dialogs
from aqt.utils import tooltip
from anki.utils import is_mac

from .utils import debugLog  # debug log registered here

from typing import Optional, Dict, cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QTabWidget,
)
from PyQt6.QtGui import QKeySequence, QShortcut

from .macosCloneMenubar import macOSCloneChildMenuBar
from .fixWebviewBlackGlitch import fixWebviewBlackGlitch
from .NoShortcutFilter import NoShortcutFilter


class TabbedMainWindow(QMainWindow):
    @staticmethod
    def _makeWindowInner(window: QWidget):
        """Make MainWindow convertible to tabs.

        Note: This must be called BEFORE window is "shown" (e.g geometry is queried)
        or it will sefgault.

        ChatGPT says:
        This crash is a known foot-gun: on macOS you generally cannot “demote” a
        live top-level QMainWindow into a child widget by toggling off Qt.Window
        and dropping it into a layout. Cocoa’s NSWindow/toolbar/menubar wiring is
        already created; changing window flags + reparenting after that can corrupt
        the native window stack → segfault.
        """
        window.setWindowFlags(window.windowFlags() & ~Qt.WindowType.Window)

    def __init__(self, mw):
        super().__init__()

        self.mw = mw

        # Demote this window before anything happens
        TabbedMainWindow._makeWindowInner(mw)

        fixWebviewBlackGlitch(mw.web)

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
        self.tabs = QTabWidget()
        self.tabs.installEventFilter(NoShortcutFilter(self.tabs))
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setContentsMargins(0, 0, 0, 0)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBar().setExpanding(True)  # type: ignore
        self.tabs.setStyleSheet(
            self.tabs.styleSheet()
            + """

/* shrink tab height & padding */
QTabBar::tab {
    height: 22px;               /* try 18-24px */
    padding: 2px 8px;           /* vertical, horizontal */
    margin: 0px;
    border-bottom: 1px solid palette(mid);
    /* optional: font-size: 11px; */
}
/* compact the pane edge */
QTabWidget::pane {
    border-top: 1px solid palette(mid);
    margin: 0px;
}
/* optional: reduce left/right gaps between tabs */
QTabBar::tab + QTabBar::tab {
    margin-left: 1px;
}
QTabBar::tab:selected {
    /* set your own selected look */
    background: palette(highlight);     /* or a custom color */
    color: palette(highlight-text);
    /* remove possible focus border */
    outline: none;
}
QTabBar::tab:!selected {
    background: palette(base);
    color: palette(text);
}
"""
        )

        self.tabs.currentChanged.connect(self._onTabChange)
        self.tabs.tabCloseRequested.connect(self._onTabClose)

        if not is_mac:
            shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
            shortcut.activated.connect(self._closeCurrentTab)

        # Create and add inner windows as tab pages
        self.addAndShowInnerWindow("AnkiQt", mw)
        self.setCentralWidget(self.tabs)

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

    def addAndShowInnerWindow(self, clsName: str, window: QMainWindow):
        tabIdx = self.tabs.indexOf(window)
        if tabIdx == -1:
            TabbedMainWindow._makeWindowInner(window)
            window.windowTitleChanged.connect(
                lambda: self.tabs.setTabText(
                    self.tabs.indexOf(window), window.windowTitle()
                )
            )
            tabIdx = self.tabs.addTab(window, window.windowTitle())

            window.activateWindow = lambda: self._activateSubwindow(window)
            window.raise_ = lambda: self._raiseSubwindow(window)

            self._windowMap[clsName] = window

        self.tabs.setCurrentIndex(tabIdx)

    def selectTabIfExists(self, clsName: str):
        try:
            window = self._windowMap[clsName]
        except KeyError:
            return

        self.tabs.setCurrentWidget(window)

    def _closeCurrentTab(self):
        widget = self.tabs.currentWidget()
        if widget:
            if widget == self.mw:
                # Main widget cannot be closed with Ctrl+W
                tooltip("Main window should be closed by Alt+F4 / Cmd+Q")
                return
            widget.close()

    def _onTabChange(self, idx):
        widget = self.tabs.widget(idx)
        if widget:
            try:
                self._mru.remove(widget)
            except ValueError:
                pass
            self._mru.insert(0, widget)
            # debugLog.log("tab changed to %d (%s), mru %s" % (idx, widget, self._mru))

            if is_mac:
                macOSCloneChildMenuBar(self, cast(QMainWindow, widget))

    def _activateSubwindow(self, window: QMainWindow):
        idx = self.tabs.indexOf(window)
        if idx != -1:
            if self.tabs.currentIndex() != idx:
                self.tabs.setCurrentIndex(idx)
        self.activateWindow()

    def _raiseSubwindow(self, window: QMainWindow):
        idx = self.tabs.indexOf(window)
        if idx != -1:
            if self.tabs.currentIndex() != idx:
                self.tabs.setCurrentIndex(idx)
        self.raise_()

    def _onMarkClosed(self, w):
        try:
            self._mru.remove(w)
        except ValueError:
            pass

        for candidate in self._mru:
            # debugLog.log(" - testing candidate %s" % w)
            idx = self.tabs.indexOf(candidate)
            if idx != -1:
                # debugLog.log("    : found at index %s -> moving" % idx)
                self.tabs.setCurrentIndex(idx)
                break

        idx = self.tabs.indexOf(w)
        if idx != -1:
            debugLog.log(" - removing tab entry #%d" % idx)
            self.tabs.removeTab(idx)

    def _onTabClose(self, index: int):
        widget = self.tabs.widget(index)
        if widget:
            widget.close()

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
        if other is self.tabs.currentWidget():
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
