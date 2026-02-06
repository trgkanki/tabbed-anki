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
# tabbed v26.1.19i98
#
# Copyright: trgk (phu54321@naver.com)
# License: GNU AGPL, version 3 or later;
# See http://www.gnu.org/licenses/agpl.html


from .utils import openChangelog
from .utils import uuid  # duplicate UUID checked here
from .utils import debugLog  # debug log registered here
from .utils.configrw import getConfig

from aqt import mw, dialogs, gui_hooks
from typing import Optional, Dict, List, cast
from PyQt6 import sip
from PyQt6.QtCore import Qt, QEvent, QObject, QTimer
from PyQt6.QtWidgets import QMainWindow, QTabBar, QToolBar, QDialog, QSizePolicy


class TabManager(QObject):
    def __init__(self, main_window: QMainWindow):
        super().__init__()
        self.mw = main_window
        self._windowMap: Dict[str, QMainWindow] = {}  # dialog_name -> window
        self._toolbars: Dict[QMainWindow, QToolBar] = {}  # window -> toolbar
        self._tabBars: Dict[QMainWindow, QTabBar] = {}  # window -> tab bar
        self._geometry_synced_windows: List[QMainWindow] = []  # All tracked windows
        self._geometry_sync_enabled = (
            True  # Flag to temporarily disable sync during programmatic changes
        )

        # Add main window tab
        self._addAndFocusTab("Main", self.mw)

        # Hook into dialogs.markClosed for cleanup
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

        # Make the tab bar widget itself expand horizontally
        tabbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Style the tab bar
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

        # Connect signals - need to identify which window this tab bar belongs to
        tabbar.currentChanged.connect(lambda idx: self._onTabChange(idx, window))
        tabbar.tabCloseRequested.connect(
            lambda idx: self._onTabCloseRequested(idx, window)
        )

        toolbar.addWidget(tabbar)
        window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        self._toolbars[window] = toolbar
        self._tabBars[window] = tabbar

    def _syncAllTabBars(self):
        debugLog.log("Synchronizing all tab bars")
        """Synchronize all tab bars to show the same tabs in the same order."""
        # Get canonical tab list from _windowMap
        tab_names = list(self._windowMap.keys())

        for window, tabbar in self._tabBars.items():
            # Block signals during rebuild
            tabbar.blockSignals(True)

            # Clear and rebuild tabs
            while tabbar.count() > 0:
                tabbar.removeTab(0)

            for name in tab_names:
                tabbar.addTab(name)

            # Set current tab based on which window this is
            current_name = None
            for name, win in self._windowMap.items():
                if win is window:
                    current_name = name
                    break

            if current_name:
                current_idx = tab_names.index(current_name)
                tabbar.setCurrentIndex(current_idx)

            tabbar.blockSignals(False)

    def _updateCurrentTabIndicators(self, active_window: QMainWindow):
        """Update which tab is highlighted as current across all tab bars."""
        # Find the name of the active window
        active_name = None
        for name, window in self._windowMap.items():
            if window is active_window:
                active_name = name
                break

        if not active_name:
            return

        active_idx = list(self._windowMap.keys()).index(active_name)

        # Update all tab bars
        for window, tabbar in self._tabBars.items():
            tabbar.blockSignals(True)
            tabbar.setCurrentIndex(active_idx)
            tabbar.blockSignals(False)

    def _addAndFocusTab(self, name: str, window: QMainWindow):
        """Add a tab for a window and track it."""
        if name in self._windowMap:
            # Already tracked, just focus it
            window.raise_()
            window.activateWindow()
            self._updateCurrentTabIndicators(window)
            return

        # Add to window map
        self._windowMap[name] = window

        # If there are existing tracked windows, sync this new window TO their geometry
        # (before it's shown, to avoid flickering)

        sync_geometry_config = getConfig("sync_geometry")
        if sync_geometry_config.get(name, False):
            debugLog.log("_addAndFocusTab: new geometry synced window %s" % name)
            if self._geometry_synced_windows:
                reference_window = self._geometry_synced_windows[0]
                if reference_window.isVisible():
                    geom = reference_window.geometry()
                    window.setGeometry(geom)
                    debugLog.log(f"Synced new window '{name}' to existing geometry")

            # Track window for geometry sync
            if window not in self._geometry_synced_windows:
                debugLog.log("adding to _geometry_synced_windows")
                self._geometry_synced_windows.append(window)

        # Create toolbar if this window doesn't have one yet
        if window not in self._toolbars:
            self._createToolbarForWindow(window)

        # Install event filter on the window
        window.installEventFilter(self)

        # Sync all tab bars to include the new tab
        self._syncAllTabBars()
        self._updateCurrentTabIndicators(window)

        debugLog.log(f"Added tab '{name}'")

    def _removeTab(self, name: str):
        """Remove a tab and stop tracking the window."""
        if name not in self._windowMap:
            return

        window = self._windowMap[name]

        # Remove from tracking
        if window in self._geometry_synced_windows:
            self._geometry_synced_windows.remove(window)

        # Remove toolbar if this window is closing
        if window in self._toolbars:
            window.removeToolBar(self._toolbars[window])
            del self._toolbars[window]
            del self._tabBars[window]

        # Remove event filter
        window.removeEventFilter(self)

        # Remove from window map
        del self._windowMap[name]

        # Sync remaining tab bars
        self._syncAllTabBars()

        debugLog.log(f"Removed tab '{name}'")

    def _onTabChange(self, index: int, source_window: QMainWindow):
        """Handle tab selection change from any tab bar."""
        if index < 0:
            return

        # Get tab name from any tab bar (they're all synced)
        tab_name = list(self._windowMap.keys())[index]

        if tab_name not in self._windowMap:
            return

        target_window = self._windowMap[tab_name]

        # Raise and activate the target window
        target_window.raise_()
        target_window.activateWindow()

        # Update current tab indicators across all tab bars
        self._updateCurrentTabIndicators(target_window)

        debugLog.log(f"Switched to tab '{tab_name}'")

    def _onTabCloseRequested(self, index: int, source_window: QMainWindow):
        """Handle close button click on a tab."""
        if index < 0:
            return

        # Get tab name from index (all tab bars are synced)
        tab_name = list(self._windowMap.keys())[index]
        if tab_name not in self._windowMap:
            return

        window = self._windowMap[tab_name]

        # Close the window (this will trigger dialogs.markClosed)
        if window is not self.mw:
            window.close()
        debugLog.log(f"Close requested for tab '{tab_name}'")

    def _syncWindowPositions(self, reference_window: QMainWindow):
        """Synchronize all tracked windows to the reference window's position and size."""
        if not self._geometry_sync_enabled:
            return

        geom = reference_window.geometry()

        # Temporarily disable sync to prevent recursive updates
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
            # Sync all windows on move/resize (only if source window is visible)
            if (
                isinstance(source, QMainWindow)
                and source in self._geometry_synced_windows
            ):
                if source.isVisible():
                    self._syncWindowPositions(source)

        elif event.type() == QEvent.Type.WindowActivate:
            # Update tab selection when window is activated
            if isinstance(source, QMainWindow) and source in self._windowMap.values():
                debugLog.log(f"WindowActivate: {source}")
                self._updateCurrentTabIndicators(source)

        return super().eventFilter(a0, a1)

    def _hookDialogsClosed(self):
        """Hook into dialogs.markClosed to clean up tabs."""
        _old_mark_closed = dialogs.markClosed

        def new_mark_closed(name: str):
            debugLog.log(f"dialogs.markClosed called: {name}")
            result = _old_mark_closed(name)

            # Remove tab for this window - check if TabManager still exists
            _tab_manager._removeTab(name)

            return result

        dialogs.markClosed = new_mark_closed


# Global tab manager instance
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
