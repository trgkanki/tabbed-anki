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
# tabbed-anki v20.5.4i8
#
# Copyright: trgk (phu54321@naver.com)
# License: GNU AGPL, version 3 or later;
# See http://www.gnu.org/licenses/agpl.html

from aqt.editor import Editor
from anki.hooks import wrap
from aqt.utils import askUser
from aqt import mw


from .utils import openChangelog
from .utils import uuid  # duplicate UUID checked here
from .utils import debugLog  # debug log registered here

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
)

# ---------- Inner windows (behave like "pages") ----------


def makeWindowInner(window: QWidget):
    window.setWindowFlags(window.windowFlags() & ~Qt.WindowType.Window)


class NewMainWindow(QMainWindow):
    def __init__(self, mw: QMainWindow):
        super().__init__()

        self.mw = mw

        self.setWindowTitle(mw.windowTitle())
        self.resize(mw.size())

        # intercept other messages
        mw.show = lambda: self.show()
        mw.activateWindow = lambda: self.activateWindow()
        mw.raise_ = lambda: self.raise_()
        mw.hide = lambda: self.hide()
        oldSetTitle = mw.setWindowTitle

        def newSetTitle(a0: Optional[str]):
            self.setWindowTitle(a0)
            oldSetTitle(a0)

        mw.setWindowTitle = newSetTitle

        # Tab widget becomes the central area, tabs on top by default
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setContentsMargins(0, 0, 0, 0)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)

        self.tabs.setStyleSheet(
            self.tabs.styleSheet()
            + """

/* shrink tab height & padding */
QTabBar::tab {
    height: 22px;               /* try 18-24px */
    padding: 2px 8px;           /* vertical, horizontal */
    margin: 0px;
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
    background: palette(button);     /* or a custom color */
    color: palette(button-text);
    /* remove possible focus border */
    outline: none;
}
QTabBar::tab:hover {
    background: palette(midlight);
}
QTabBar::tab:!selected {
    background: palette(base);
    color: palette(text);
}
"""
        )
        self.tabs.tabCloseRequested.connect(self.close_tab)

        # Create and add inner windows as tab pages
        self.addInnerWindow(mw)
        self.setCentralWidget(self.tabs)

        # (Optional) programmatic navigation example:
        # tabs.setCurrentIndex(1)  # select "InnerWindow2" on startup

    def addInnerWindow(self, window: QWidget):
        window.setWindowFlags(window.windowFlags() & ~Qt.WindowType.Window)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.tabs.addTab(window, window.windowTitle())
        window.windowTitleChanged.connect(
            lambda: self.tabs.setTabText(
                self.tabs.indexOf(window), window.windowTitle()
            )
        )
        window.destroyed.connect(lambda: self._remove_widget_tab(window))

    def _remove_widget_tab(self, w):
        idx = self.tabs.indexOf(w)
        if idx != -1:
            self.tabs.removeTab(idx)

    def close_tab(self, index: int):
        widget = self.tabs.widget(index)
        if widget:
            widget.close()

    def closeEvent(self, event):
        self.mw.close()
        event.ignore()


newMainWindow: Optional[NewMainWindow] = NewMainWindow(mw)
