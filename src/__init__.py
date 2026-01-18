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
# tabbed v25.8.22i156
#
# Copyright: trgk (phu54321@naver.com)
# License: GNU AGPL, version 3 or later;
# See http://www.gnu.org/licenses/agpl.html


from .utils import openChangelog
from .utils import uuid  # duplicate UUID checked here
from .utils import debugLog  # debug log registered here

from aqt import mw, dialogs, gui_hooks
from typing import Optional, Dict, List, cast
from PyQt6.QtCore import Qt, QEvent, QObject
from PyQt6.QtWidgets import (
    QMainWindow,
    QTabBar,
    QWidget,
    QVBoxLayout,
    QDialog,
)


class TabOverlay(QMainWindow):
    def __init__(self, main_window: QMainWindow):
        super().__init__()

        self.mw = main_window
        self._windowMap: Dict[str, QMainWindow] = {}  # dialog_name -> window
        self._tabIndexMap: Dict[str, int] = {}  # dialog_name -> tab_index
        self._tracked_windows: List[QMainWindow] = []  # All tracked windows in z-order
        self._sync_enabled = (
            True  # Flag to temporarily disable sync during programmatic changes
        )

        # Make the window frameless and transparent
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Create the Tab Bar
        self.tabs = QTabBar()
        self.tabs.setMovable(True)  # Allow drag-and-drop reordering
        self.tabs.setTabsClosable(True)  # Add close buttons to tabs
        self.tabs.setExpanding(False)  # Don't expand tabs to fill width
        self.tabs.currentChanged.connect(self._onTabChange)
        self.tabs.tabCloseRequested.connect(self._onTabCloseRequested)

        # Set initial opacity
        self.setWindowOpacity(0.4)

        # Install event filter on tabs for hover detection
        self.tabs.installEventFilter(self)

        # Style the tab bar to be more compact
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                padding: 4px 12px;
                font-size: 10px;
                min-width: 80px;
                max-width: 150px;
            }
            QTabBar::tab:selected {
                font-weight: bold;
            }
            """)

        # Add main window tab
        self._addAndFocusTab("Main", self.mw)

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Set tab bar dimensions
        self.setFixedHeight(30)  # Smaller height
        self._updateWidth()

        # Install event filters
        self.mw.installEventFilter(self)
        self.update_position()

        # Hook into dialogs.markClosed for cleanup
        self._hookDialogsClosed()

    def _addAndFocusTab(self, name: str, window: QMainWindow) -> int:
        """Add a tab for a window and track it."""
        if name in self._windowMap:
            # Window already tracked, just activate it
            idx = self._tabIndexMap[name]
            self.tabs.setCurrentIndex(idx)
            return idx

        # Add tab
        idx = self.tabs.addTab(name)
        self._windowMap[name] = window
        self._tabIndexMap[name] = idx
        self.tabs.setCurrentIndex(idx)

        # Track window for geometry sync
        if window not in self._tracked_windows:
            self._tracked_windows.append(window)

        # Install event filter on the window
        window.installEventFilter(self)

        self._updateWidth()
        self.update_position()

        debugLog.log(f"Added tab '{name}' at index {idx}")
        return idx

    def _removeTab(self, name: str):
        """Remove a tab and stop tracking the window."""
        if name not in self._windowMap:
            return

        window = self._windowMap[name]
        idx = self._tabIndexMap[name]

        # Remove from tracking
        if window in self._tracked_windows:
            self._tracked_windows.remove(window)

        # Remove event filter
        window.removeEventFilter(self)

        # Block signals to prevent currentChanged from firing during tab removal
        self.tabs.blockSignals(True)

        # Remove tab
        self.tabs.removeTab(idx)

        # Update maps
        del self._windowMap[name]
        del self._tabIndexMap[name]

        # Rebuild tab index map
        self._rebuildTabIndexMap()

        self._updateWidth()

        # Re-enable signals
        self.tabs.blockSignals(False)

        debugLog.log(f"Removed tab '{name}'")

    def _rebuildTabIndexMap(self):
        """Rebuild the tab index map after tab removal."""
        self._tabIndexMap.clear()
        for idx in range(self.tabs.count()):
            tab_name = self.tabs.tabText(idx)
            self._tabIndexMap[tab_name] = idx

    def _updateWidth(self):
        """Update tab bar width dynamically based on actual tab sizes."""
        # Calculate actual width needed for all tabs
        total_width = 0
        for i in range(self.tabs.count()):
            # Get the size hint for each tab
            tab_rect = self.tabs.tabRect(i)
            total_width += tab_rect.width()

        # Set min/max bounds
        width = min(1000, total_width)
        self.setFixedWidth(width)

    def _onTabChange(self, index: int):
        """Handle tab selection change."""
        if index < 0:
            return

        tab_name = self.tabs.tabText(index)
        if tab_name not in self._windowMap:
            return

        window = self._windowMap[tab_name]

        # Raise and activate window
        window.raise_()
        window.activateWindow()

        debugLog.log(f"Switched to tab '{tab_name}'")

    def _onTabCloseRequested(self, index: int):
        """Handle close button click on a tab."""
        if index < 0:
            return

        tab_name = self.tabs.tabText(index)
        if tab_name not in self._windowMap:
            return

        window = self._windowMap[tab_name]

        # Close the window (this will trigger dialogs.markClosed)
        if window is not self.mw:
            window.close()
        debugLog.log(f"Close requested for tab '{tab_name}'")

    def _syncWindowPositions(self, reference_window: QMainWindow):
        """Synchronize all tracked windows to the reference window's position and size."""
        if not self._sync_enabled:
            return

        geom = reference_window.geometry()

        # Temporarily disable sync to prevent recursive updates
        self._sync_enabled = False
        try:
            for window in self._tracked_windows:
                if window is not reference_window:
                    window.setGeometry(geom)
        finally:
            self._sync_enabled = True

    def update_position(self):
        """Position the tab overlay at the top of a tracked window."""
        if not self._tracked_windows:
            return

        # Use any tracked window as reference (they all have same geometry due to sync)
        reference_window = self._tracked_windows[0]
        geom = reference_window.geometry()

        # Center horizontally on the window
        center_x = geom.x() + (geom.width() // 2) - (self.width() // 2)
        # Position at the top, overlapping slightly
        top_y = geom.y() - self.height() + 2

        self.move(center_x, top_y)

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        """Monitor events from tracked windows."""
        if a0 is None or a1 is None:
            return False

        source = a0
        event = a1

        # Handle hover events on the tab bar for opacity changes
        if source is self.tabs:
            if event.type() == QEvent.Type.Enter:
                self.setWindowOpacity(1.0)
            elif event.type() == QEvent.Type.Leave:
                self.setWindowOpacity(0.4)

        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            # If main window or any tracked window moves/resizes, sync all windows
            if isinstance(source, QMainWindow) and source in self._tracked_windows:
                self._syncWindowPositions(source)
                self.update_position()

        elif event.type() == QEvent.Type.WindowActivate:
            # Window was activated, update tab selection
            if isinstance(source, QMainWindow) and source in self._tracked_windows:
                debugLog.log(f"WindowActivate: {source}")

                # Update tab selection to match
                for name, window in self._windowMap.items():
                    if window is source:
                        idx = self._tabIndexMap[name]
                        if self.tabs.currentIndex() != idx:
                            debugLog.log(
                                f"Updating tab selection to '{name}' (index {idx})"
                            )
                            # Block signals to prevent triggering _onTabChange
                            self.tabs.blockSignals(True)
                            self.tabs.setCurrentIndex(idx)
                            self.tabs.blockSignals(False)
                        break
                # Show and raise the overlay when any tracked window is activated
                self.show()
                self.raise_()
                self.update_position()

        elif event.type() == QEvent.Type.WindowDeactivate:
            # Check if focus moved outside Anki windows
            if isinstance(source, QMainWindow) and source in self._tracked_windows:
                # Hide overlay when any tracked window is deactivated
                active_window = None
                for window in self._tracked_windows:
                    if window.isActiveWindow():
                        active_window = window
                        break
                if active_window is None:
                    self.hide()

        return super().eventFilter(a0, a1)

    def _hookDialogsClosed(self):
        """Hook into dialogs.markClosed to clean up tabs."""
        _old_mark_closed = dialogs.markClosed

        def new_mark_closed(name: str):
            debugLog.log(f"dialogs.markClosed called: {name}")
            result = _old_mark_closed(name)

            # Remove tab for this window - check if TabOverlay still exists
            global _tab_overlay
            if _tab_overlay is not None:
                _tab_overlay._removeTab(name)

            return result

        dialogs.markClosed = new_mark_closed


# Global tab overlay instance
_tab_overlay: Optional[TabOverlay] = None

wrappedDialogs = ["AddCards", "Browser", "EditCurrent", "DeckStats", "NewDeckStats"]

_wrappedSet = set()

_oldDialogsOpen = dialogs.open


def wrapClass(clsName, cls):
    oldShow = cls.show

    def newShow(self):
        if _tab_overlay:
            _tab_overlay._addAndFocusTab(clsName, self)
        oldShow(self)

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

####


def init_tab_overlay():
    """Initialize the tab overlay when main window is shown."""
    global _tab_overlay

    if _tab_overlay is None and mw is not None:
        _tab_overlay = TabOverlay(mw)
        _tab_overlay.show()
        debugLog.log("Tab overlay initialized")


def cleanup_tab_overlay():
    """Cleanup the tab overlay when main window is destroyed."""
    global _tab_overlay

    if _tab_overlay is not None:
        debugLog.log("Cleaning up tab overlay")

        # Remove event filters from all tracked windows
        for window in _tab_overlay._tracked_windows:
            window.removeEventFilter(_tab_overlay)

        # Close and delete the overlay
        _tab_overlay.close()
        _tab_overlay.deleteLater()
        _tab_overlay = None


# Hook to main window's lifecycle events
original_showEvent = mw.showEvent
original_hideEvent = mw.hideEvent


def new_showEvent(event):
    original_showEvent(event)
    init_tab_overlay()


def new_hideEvent(event):
    cleanup_tab_overlay()
    original_hideEvent(event)


mw.showEvent = new_showEvent
mw.hideEvent = new_hideEvent
