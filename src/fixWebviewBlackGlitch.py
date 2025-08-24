from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt
from aqt.webview import AnkiWebView


def fixWebviewBlackGlitch(web: QWebEngineView):
    web.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)


# macOS QWebEngineView fix

_oldInit = AnkiWebView.__init__


def newInit(self, *args, **kwargs):
    _oldInit(self, *args, **kwargs)
    fixWebviewBlackGlitch(self)


AnkiWebView.__init__ = newInit
