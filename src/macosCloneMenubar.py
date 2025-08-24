from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow, QMenuBar, QMenu, QWidget


def macOSCloneChildMenuBar(parent: QMainWindow, child: QMainWindow):
    pmb = parent.menuBar() or QMenuBar(parent)
    if parent.menuBar() is None:
        parent.setMenuBar(pmb)
    pmb.clear()

    cmb = child.menuBar()
    if cmb is None:
        return  # nothing to merge

    insertedMenus = []

    # Create sibling menus on parent and reuse QAction objects
    for topAct in cmb.actions():
        menu = topAct.menu()
        if not menu:
            # top-level action without submenu (rare) — add directly
            pmb.addAction(topAct)
            continue

        clone = QMenu(menu.title(), parent)
        # carry over icon/shortcut-hints if desired
        clone.setIcon(menu.icon())

        for act in menu.actions():
            # QAction can be added to multiple menus
            clone.addAction(act)

        pmb.addMenu(clone)
        insertedMenus.append(clone)

    # Optional: ensure shortcuts work from the outer window, too.
    # Many QAction defaults use WindowShortcut; keep them alive on the active top-level:
    for m in insertedMenus:
        for act in m.actions():
            act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            # or WidgetWithChildrenShortcut if you prefer scoping to the parent window
