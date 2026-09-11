# Copyright (C) 2020 Hyun Woo Park
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# -*- coding: utf-8 -*-
#
# tabbed v26.7.12i31
#
# Copyright: trgk (phu54321@naver.com)
# License: GNU AGPL, version 3 or later;
# See http://www.gnu.org/licenses/agpl.html


from .utils import openChangelog
from .utils import uuid  # duplicate UUID checked here
from .utils import debugLog  # debug log registered here
from .utils.configrw import getConfig

from aqt import mw, dialogs, gui_hooks
from typing import Optional, Dict, List, NamedTuple, cast
from PyQt6 import sip
from PyQt6.QtCore import Qt, QEvent, QObject, QTimer
from PyQt6.QtWidgets import (
    QMainWindow,
    QTabBar,
    QToolBar,
    QDialog,
    QSizePolicy,
    QWidget,
)

import sys
import ctypes
import inspect


def force_activate_window(qwindow):
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        SW_RESTORE = 9

        hwnd = int(qwindow.winId())

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

        foreground = user32.GetForegroundWindow()
        current_thread = kernel32.GetCurrentThreadId()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)

        user32.AttachThreadInput(current_thread, foreground_thread, True)
        try:
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        finally:
            user32.AttachThreadInput(current_thread, foreground_thread, False)

    qwindow.raise_()
    qwindow.activateWindow()


class WindowInfo(NamedTuple):
    """kind is Anki's own dialog-type name (stable; used for config lookups
    and to match dialogs.markClosed's argument). label is what's shown on
    the tab, and only equals kind for the first window of that kind -- see
    TabManager._makeLabel."""

    kind: str
    label: str


class TabManager(QObject):
    def __init__(self, main_window: QMainWindow):
        super().__init__()
        self.mw = main_window
        self._windowMap: Dict[QMainWindow, WindowInfo] = {}
        self._kindCounters: Dict[str, int] = {}
        self._toolbars: Dict[QMainWindow, QToolBar] = {}
        self._tabBars: Dict[QMainWindow, QTabBar] = {}
        # only windows opted into sync_geometry (see _addAndFocusTab), not
        # every tracked window
        self._geometry_synced_windows: List[QMainWindow] = []
        # disabled temporarily while we set geometry programmatically, so
        # that doesn't itself re-trigger a sync (see _syncWindowPositions)
        self._geometry_sync_enabled = True

        self._addAndFocusTab("Main", self.mw)
        self._hookDialogsClosed()

    def _createToolbarForWindow(self, window: QMainWindow) -> tuple[QToolBar, QTabBar]:
        """Create and attach a toolbar with tab bar to a window."""
        toolbar = QToolBar("Tabs")
        toolbar.setMovable(False)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.layout().setContentsMargins(0, 0, 0, 0)
        toolbar.layout().setSpacing(0)
        toolbar.setFloatable(False)
        toolbar.setAllowedAreas(Qt.ToolBarArea.TopToolBarArea)
        toolbar.setStyleSheet("""
        QToolBar {
            padding: 0px;
            spacing: 0px;
            border: none;
        }
        """)

        tabbar = QTabBar()
        tabbar.setMovable(True)
        tabbar.setTabsClosable(True)
        tabbar.setContentsMargins(0, 0, 0, 0)

        tabbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        tabbar.setStyleSheet("""
        /* shrink tab height & padding */
        QTabBar::tab {
            height: 22px;               /* try 18-24px */
            padding: 0px 8px;           /* vertical, horizontal */
            margin: 0px;
            border-bottom: 1px solid palette(mid);
            border-right: 1px solid palette(mid);
            /* optional: font-size: 11px; */
        }
        QTabBar::tab:last {
            border-right: none;
        }
        /* compact the pane edge */
        QTabWidget::pane {
            border-top: 1px solid palette(mid);
            margin: 0px;
            padding: 0px;
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
        """)

        # `window` is captured here so the callback knows which window this
        # tab bar belongs to -- the signal itself doesn't carry that
        tabbar.currentChanged.connect(lambda idx: self._onTabChange(idx, window))
        tabbar.tabCloseRequested.connect(
            lambda idx: self._onTabCloseRequested(idx, window)
        )

        toolbar.addWidget(tabbar)
        window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        self._toolbars[window] = toolbar
        self._tabBars[window] = tabbar

    def _syncAllTabBars(self):
        """Synchronize all tab bars to show the same tabs in the same order."""
        debugLog.log("Synchronizing all tab bars")
        # dict preserves insertion order, so this doubles as the tab order
        windows = list(self._windowMap.keys())
        labels = [self._windowMap[w].label for w in windows]

        for window, tabbar in self._tabBars.items():
            # avoid spurious _onTabChange while we tear down and rebuild tabs
            tabbar.blockSignals(True)

            while tabbar.count() > 0:
                tabbar.removeTab(0)

            for label in labels:
                tabbar.addTab(label)

            if window in self._windowMap:
                current_idx = windows.index(window)
                tabbar.setCurrentIndex(current_idx)

            tabbar.blockSignals(False)

    def _updateCurrentTabIndicators(self, active_window: QMainWindow):
        """Update which tab is highlighted as current across all tab bars."""
        if active_window not in self._windowMap:
            return

        active_idx = list(self._windowMap.keys()).index(active_window)

        for window, tabbar in self._tabBars.items():
            tabbar.blockSignals(True)
            tabbar.setCurrentIndex(active_idx)
            tabbar.blockSignals(False)

    def _makeLabel(self, name: str) -> str:
        """Build a display label for a new window of kind `name`, disambiguating
        against any other currently-open windows of the same kind (e.g. multiple
        Browser windows opened via an addon that allows it).

        Numbered by a per-kind counter (`_kindCounters`) that only ever
        increases while at least one window of that kind stays open, rather
        than by how many are currently open: opening a 4th AddCards after
        the 1st has already closed gets "AddCards (4)", not a reused
        "AddCards (3)" that's still someone else's tab. The counter is
        reset (see `_removeTabByWindow`) once every window of that kind has
        closed, so the next one to open starts clean at the bare name
        again.
        """
        count = self._kindCounters.get(name, 0) + 1
        self._kindCounters[name] = count
        return name if count == 1 else f"{name} ({count})"

    def _addAndFocusTab(self, name: str, window: QMainWindow):
        """Add a tab for a window and track it.

        `name` is the dialog *kind* (e.g. "Browser"); several windows of the
        same kind may be tracked at once (e.g. via an addon that allows
        opening multiple Browsers), so tracking is keyed by window instance,
        not by name. Only re-showing the *same* instance is treated as
        "already tracked".
        """
        if window in self._windowMap:
            window.raise_()
            window.activateWindow()
            self._updateCurrentTabIndicators(window)
            return

        label = self._makeLabel(name)
        self._windowMap[window] = WindowInfo(kind=name, label=label)

        # sync geometry to existing windows before this one is shown, to
        # avoid a visible jump into place
        sync_geometry_config = getConfig("sync_geometry")
        if sync_geometry_config.get(name, False):
            debugLog.log("_addAndFocusTab: new geometry synced window %s" % name)
            if self._geometry_synced_windows:
                reference_window = self._geometry_synced_windows[0]
                if reference_window.isVisible():
                    geom = reference_window.geometry()
                    window.setGeometry(geom)
                    debugLog.log(f"Synced new window '{name}' to existing geometry")

            if window not in self._geometry_synced_windows:
                debugLog.log("adding to _geometry_synced_windows")
                self._geometry_synced_windows.append(window)

        if window not in self._toolbars:
            self._createToolbarForWindow(window)

        window.installEventFilter(self)

        self._syncAllTabBars()
        self._updateCurrentTabIndicators(window)

        debugLog.log(f"Added tab '{label}'")

    def _removeTabByWindow(self, window: QMainWindow):
        """Remove a tab and stop tracking a specific window instance."""
        if window not in self._windowMap:
            return

        kind = self._windowMap[window].kind
        label = self._windowMap[window].label

        if window in self._geometry_synced_windows:
            self._geometry_synced_windows.remove(window)

        if window in self._toolbars:
            window.removeToolBar(self._toolbars[window])
            del self._toolbars[window]
            del self._tabBars[window]

        window.removeEventFilter(self)
        del self._windowMap[window]

        # Once no window of this kind remains open, reset its label counter
        # so the next one opened starts clean at the bare name again.
        if not any(info.kind == kind for info in self._windowMap.values()):
            self._kindCounters.pop(kind, None)

        self._syncAllTabBars()
        debugLog.log(f"Removed tab '{label}'")

    def _removeTabFallback(self, name: str):
        """Fallback path: remove the tab for a closed dialog of kind `name`
        when the actual closing instance couldn't be determined (see
        `_hookDialogsClosed`, which normally resolves the instance directly
        and calls `_removeTabByWindow` instead of this).

        Unambiguous when only one window of `name` is tracked. If several
        are tracked and we still ended up here, we don't know which one
        actually closed -- guessing would risk tearing down a still-open
        window's tab (the exact bug this replaced), so we log and leave
        tracking alone rather than remove the wrong one.
        """
        candidates = [w for w, info in self._windowMap.items() if info.kind == name]
        if not candidates:
            return
        if len(candidates) > 1:
            debugLog.log(
                f"_removeTabFallback: {len(candidates)} windows of kind '{name}' tracked "
                "but could not identify which one closed; leaving tabs as-is"
            )
            return
        self._removeTabByWindow(candidates[0])

    def _onTabChange(self, index: int, source_window: QMainWindow):
        """Handle tab selection change from any tab bar."""
        if index < 0:
            return

        # all tab bars are kept in sync, so this index applies to any of them
        windows = list(self._windowMap.keys())
        if index >= len(windows):
            return
        target_window = windows[index]

        force_activate_window(target_window)
        self._updateCurrentTabIndicators(target_window)

        debugLog.log(f"Switched to tab '{self._windowMap[target_window].label}'")

    def _onTabCloseRequested(self, index: int, source_window: QMainWindow):
        """Handle close button click on a tab."""
        if index < 0:
            return

        windows = list(self._windowMap.keys())
        if index >= len(windows):
            return
        window = windows[index]

        # closing triggers dialogs.markClosed, which is what actually
        # removes this window's tracking/tab (see _hookDialogsClosed)
        if window is not self.mw:
            window.close()
        debugLog.log(f"Close requested for tab '{self._windowMap[window].label}'")

    def _syncWindowPositions(self, reference_window: QMainWindow):
        """Synchronize all tracked windows to the reference window's position and size."""
        if not self._geometry_sync_enabled:
            return

        geom = reference_window.geometry()

        # disabled while applying, so setGeometry below doesn't re-trigger this
        self._geometry_sync_enabled = False
        try:
            for window in self._geometry_synced_windows:
                if window is not reference_window:
                    window.setGeometry(geom)
        finally:
            self._geometry_sync_enabled = True

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        """Monitor events from tracked windows."""
        if a0 is None or a1 is None:
            return False

        source = a0
        event = a1

        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            if (
                isinstance(source, QMainWindow)
                and source in self._geometry_synced_windows
            ):
                if source.isVisible():  # geometry isn't meaningful while hidden
                    self._syncWindowPositions(source)

        elif event.type() == QEvent.Type.WindowActivate:
            if isinstance(source, QMainWindow) and source in self._windowMap:
                debugLog.log(f"WindowActivate: {source}")
                self._updateCurrentTabIndicators(source)

        return super().eventFilter(a0, a1)

    def _hookDialogsClosed(self):
        """Hook into dialogs.markClosed to clean up tabs."""
        _old_mark_closed = dialogs.markClosed

        def new_mark_closed(name: str):
            debugLog.log(f"dialogs.markClosed called: {name}")

            # Anki reports only which *kind* closed, but always calls
            # markClosed from an instance method of the dialog, so the
            # instance can be recovered from the stack. The whole stack is
            # searched rather than just our caller, since another addon may
            # also wrap markClosed and sit in between.
            creator = dialogs._dialogs.get(name, (None,))[0]
            if not isinstance(creator, type):
                creator = QWidget  # a few kinds register a factory function
            closing = None
            frame = inspect.currentframe()
            frame = frame.f_back if frame else None
            while frame is not None:
                candidate = frame.f_locals.get("self")
                if isinstance(candidate, creator):
                    # Also bound as `self` for 354407385 "Opening the same
                    # window multiple time", which reads the closing dialog
                    # from stack()[2].frame.f_locals['self'] and would
                    # otherwise land on this frame and find nothing. Left
                    # unbound when the search fails: binding None instead
                    # makes its lookup match no open dialog, which strands
                    # the entry in its _openDialogs so allClosed() never
                    # goes true and Anki can't quit or switch profiles.
                    closing = self = candidate
                    break
                frame = frame.f_back

            result = _old_mark_closed(name)

            if closing is not None:
                _tab_manager._removeTabByWindow(closing)
            else:
                _tab_manager._removeTabFallback(name)

            return result

        dialogs.markClosed = new_mark_closed


_tab_manager = TabManager(mw)

wrappedDialogs = ["AddCards", "Browser", "EditCurrent", "DeckStats", "NewDeckStats"]

_wrappedSet = set()

_oldDialogsOpen = dialogs.open


def wrapClass(clsName, cls):
    oldShow = cls.show

    def newShow(self):
        def callback():
            if not sip.isdeleted(self):
                _tab_manager._addAndFocusTab(clsName, self)

        QTimer.singleShot(0, callback)
        return oldShow(self)

    cls.show = newShow


def newDialogsOpen(name: str, *args, **kwargs):
    if name in wrappedDialogs:
        if name not in _wrappedSet:
            creator, instance = dialogs._dialogs[name]
            if issubclass(creator, QDialog):
                debugLog.log(
                    "error: %s is QDialog, which cannot be made as a tab." % (creator,)
                )
            else:
                wrapClass(name, creator)
            _wrappedSet.add(name)
    return _oldDialogsOpen(name, *args, **kwargs)


dialogs.open = newDialogsOpen
