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


from aqt import dialogs
from aqt.addcards import AddCards
from anki.hooks import wrap

from .utils import openChangelog
from .utils import uuid  # duplicate UUID checked here
from .utils import debugLog  # debug log registered here

from PyQt6.QtWidgets import (
    QDialog,
)

from .TabbedMainWindow import newMainWindow
from . import addCardsSaveHook


wrappedDialogs = ["AddCards", "Browser", "EditCurrent"]

_wrappedSet = set()

_oldDialogsOpen = dialogs.open


def wrapClass(clsName, cls):
    oldShow = cls.show

    def newShow(self):
        newMainWindow.addAndShowInnerWindow(clsName, self)
        oldShow(self)

    cls.show = newShow


def newDialogsOpen(name: str, *args, **kwargs):
    if name in wrappedDialogs:
        if name not in _wrappedSet:
            (creator, instance) = dialogs._dialogs[name]
            if issubclass(creator, QDialog):
                debugLog.log(
                    "error: %s is QDialog, which cannot be made as a tab." % (creator,)
                )
            else:
                wrapClass(name, creator)
            _wrappedSet.add(name)
    _oldDialogsOpen(name, *args, **kwargs)


dialogs.open = newDialogsOpen
