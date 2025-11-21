from aqt import mw, dialogs
from aqt.utils import tooltip
from anki.utils import is_mac, is_win

from .utils import debugLog  # debug log registered here

from typing import Optional, Dict, cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow, QMenuBar, QTabWidget, QMdiSubWindow
from PyQt6.QtGui import QKeySequence, QShortcut
from .NoShortcutFilter import NoShortcutFilter


class TabMdiSubWindow(QMdiSubWindow):
    def __init__(self, childWindow: QMainWindow, parent=None):
        super().__init__(parent)
        # Remove window decorations since we're using it as a container
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWidget(childWindow)


_tabbarStyle = """

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
    background: palette(highlight);
    color: palette(highlight-text);
    /* remove possible focus border */
    outline: none;
}
QTabBar::tab:!selected {
    background: palette(base);
    color: palette(text);
}
"""


class TabbedMainWindow(QMainWindow):
    @staticmethod
    def _makeWindowInner(window: QMainWindow):
        """Make adjustment to embedded window so it stays sanely within the tabbedmainwindow."""

        # macOS has single global menubar for everything. unfortunately I don't know how to
        # properly manage menubar across multiple embedded window. Here we just dictate
        # the ui to show embedded menubar instead.
        menuBar = window.menuBar()
        if menuBar:
            menuBar.setNativeMenuBar(False)

    def __init__(self, mw):
        super().__init__()

        self.mw = mw
        self._mru = []
        self._windowMap: Dict[str, QMainWindow] = {}

        self.tabs = QTabWidget()
        self.tabs.installEventFilter(NoShortcutFilter(self.tabs))
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setContentsMargins(0, 0, 0, 0)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBar().setExpanding(True)  # type: ignore
        self.tabs.setStyleSheet(self.tabs.styleSheet() + _tabbarStyle)
        self.tabs.currentChanged.connect(self._onTabChange)
        self.tabs.tabCloseRequested.connect(self._onTabClose)
        self.setCentralWidget(self.tabs)

        if not is_mac:
            shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
            shortcut.activated.connect(self._closeCurrentTab)

        # Create and add inner windows as tab pages
        self.addAndShowInnerWindow("AnkiQt", mw)

        self.setWindowTitle("Anki")
        # self.resize(mw.size())  TODO: resize according to anki layout.
        self.setWindowIcon(mw.windowIcon())

        # window closed handler. I think this is the best way of being notified
        # when the window is closed.
        #
        # note that we cannot use WA_DeleteOnClose + deleted event commbo, since
        # anki simply isn't built upon that. It has multiple leaking reference
        # to closed window, so it shouldn't be deleted. Maybe we can override
        # `closeEvent` instead, but I doubt that is stable either.
        oldMarkClosed = dialogs.markClosed

        def newMarkClosed(name: str):
            # debugLog.log("newMarkClosed %s" % (name,))
            oldMarkClosed(name)
            try:
                window = self._windowMap[name]
            except KeyError:
                return
            # debugLog.log(" - removing window %s" % (window,))
            self._onMarkClosed(window)

        dialogs.markClosed = newMarkClosed

        # Show this window when mw should be shown.
        oldShow = mw.show
        mw.show = lambda: (self.show(), oldShow())
        mw.hide = self.hide

    def _getWindowAssociatedMdiSubWindow(
        self, window: QMainWindow
    ) -> Optional[TabMdiSubWindow]:
        tabCount = self.tabs.count()
        for i in range(tabCount):
            w = self.tabs.widget(i)
            w = cast(TabMdiSubWindow, w)
            if w.widget() is window:
                return w

        return None

    def addAndShowInnerWindow(self, clsName: str, window: QMainWindow):
        mdiWindow = self._getWindowAssociatedMdiSubWindow(window)
        if not mdiWindow:
            TabbedMainWindow._makeWindowInner(window)

            mdiWindow = TabMdiSubWindow(window)
            window.windowTitleChanged.connect(
                lambda: self.tabs.setTabText(
                    self.tabs.indexOf(mdiWindow), window.windowTitle()
                )
            )
            tabIdx = self.tabs.addTab(mdiWindow, window.windowTitle())
            self.tabs.setCurrentIndex(tabIdx)

            window.activateWindow = lambda: self._activateSubwindow(window)
            window.raise_ = lambda: self._raiseSubwindow(window)

            self._windowMap[clsName] = window
        else:
            self.tabs.setCurrentWidget(mdiWindow)

    def selectTabIfExists(self, clsName: str):
        try:
            window = self._windowMap[clsName]
        except KeyError:
            return

        mdiWindow = self._getWindowAssociatedMdiSubWindow(window)
        if mdiWindow:
            self.tabs.setCurrentWidget(mdiWindow)

    def _closeCurrentTab(self):
        widget = self.tabs.currentWidget()
        if widget:
            widget = cast(TabMdiSubWindow, widget)

            if widget.widget() == self.mw:
                # Main widget cannot be closed with Ctrl+W
                tooltip("Main window should be closed by Alt+F4 / Cmd+Q")
                return
            widget.close()

    def _onTabChange(self, idx):
        widget = self.tabs.widget(idx)
        if widget:
            widget = cast(TabMdiSubWindow, widget)
            subWindow = widget.widget()
            try:
                self._mru.remove(subWindow)
            except ValueError:
                pass
            self._mru.insert(0, subWindow)
            # debugLog.log("tab changed to %d (%s), mru %s" % (idx, widget, self._mru))

    def _activateSubwindow(self, window: QMainWindow):
        mdiWindow = self._getWindowAssociatedMdiSubWindow(window)
        if mdiWindow and self.tabs.currentWidget() is not mdiWindow:
            self.tabs.setCurrentWidget(mdiWindow)
        self.activateWindow()

    def _raiseSubwindow(self, window: QMainWindow):
        mdiWindow = self._getWindowAssociatedMdiSubWindow(window)
        if mdiWindow and self.tabs.currentWidget() is not mdiWindow:
            self.tabs.setCurrentWidget(mdiWindow)
        self.raise_()

    def _onMarkClosed(self, w):
        try:
            self._mru.remove(w)
        except ValueError:
            pass

        for candidate in self._mru:
            mdiWindow = self._getWindowAssociatedMdiSubWindow(candidate)
            # debugLog.log(" - testing candidate %s" % w)
            idx = self.tabs.indexOf(mdiWindow)
            if idx != -1:
                # debugLog.log("    : found at index %s -> moving" % idx)
                self.tabs.setCurrentIndex(idx)
                break

        mdiWindow = self._getWindowAssociatedMdiSubWindow(w)
        if mdiWindow:
            idx = self.tabs.indexOf(mdiWindow)
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
        currentWidget = self.tabs.currentWidget()
        if currentWidget and cast(TabMdiSubWindow, currentWidget).widget() is other:
            return True

        # For anything else, defer to the other side
        return NotImplemented

    # I doubt `__ne__` is ever implemented on super class QMainWindow, but here
    # I wanna regard QMainWindow as builtin types. As we're overriding `__eq__`
    # of builtins we override `__ne__` too.
    # https://stackoverflow.com/questions/4352244/should-ne-be-implemented-as-the-negation-of-eq
    def __ne__(self, other):
        return not (self == other)


newMainWindow = TabbedMainWindow(mw)
