import json
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .workspace import apply_state, collect_state


# shadcn/ui "slate" tokens, shared with the web generator (ctw_map_gen/src/ui/styles.css).
THEMES = {
    "light": {
        "background": "#ffffff", "foreground": "#020817", "card": "#ffffff",
        "primary": "#0f172a", "primary_fg": "#f8fafc",
        "secondary": "#f1f5f9", "secondary_fg": "#0f172a", "muted": "#f1f5f9", "muted_fg": "#64748b",
        "accent": "#f1f5f9", "border": "#e2e8f0", "ring": "#020817", "destructive": "#ef4444",
    },
    "dark": {
        "background": "#020817", "foreground": "#f8fafc", "card": "#020817",
        "primary": "#f8fafc", "primary_fg": "#0f172a",
        "secondary": "#1e293b", "secondary_fg": "#f8fafc", "muted": "#1e293b", "muted_fg": "#94a3b8",
        "accent": "#1e293b", "border": "#1e293b", "ring": "#cbd5e1", "destructive": "#7f1d1d",
    },
}


def _palette(t):
    palette = QPalette()
    roles = {
        QPalette.Window: t["background"], QPalette.WindowText: t["foreground"],
        QPalette.Base: t["background"], QPalette.AlternateBase: t["muted"],
        QPalette.Text: t["foreground"], QPalette.Button: t["secondary"],
        QPalette.ButtonText: t["secondary_fg"], QPalette.ToolTipBase: t["card"],
        QPalette.ToolTipText: t["foreground"], QPalette.Highlight: t["primary"],
        QPalette.HighlightedText: t["primary_fg"], QPalette.PlaceholderText: t["muted_fg"],
        QPalette.Link: t["ring"], QPalette.BrightText: t["destructive"],
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(t["muted_fg"]))
    return palette


def _stylesheet(t, check_icon):
    return f"""
        QMainWindow, QDialog {{ background: {t['background']}; }}
        QWidget {{ font-size: 13px; }}
        QToolTip {{ background: {t['card']}; color: {t['foreground']}; border: 1px solid {t['border']}; padding: 4px; }}
        QMenuBar, QToolBar {{ background: {t['background']}; border: none; border-bottom: 1px solid {t['border']}; }}
        QMenuBar::item:selected, QMenu::item:selected, QToolButton:hover {{ background: {t['accent']}; border-radius: 4px; }}
        QMenu {{ background: {t['card']}; border: 1px solid {t['border']}; padding: 4px; }}
        QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
        QGroupBox {{ border: 1px solid {t['border']}; border-radius: 8px; margin-top: 12px; padding: 12px 10px 10px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {t['muted_fg']}; }}
        QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QListWidget, QTableWidget {{
            background: {t['background']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 4px 6px;
            selection-background-color: {t['primary']}; selection-color: {t['primary_fg']};
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {t['ring']}; }}
        QPushButton {{ background: {t['secondary']}; color: {t['secondary_fg']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px 12px; }}
        QPushButton:hover {{ background: {t['accent']}; border-color: {t['muted_fg']}; }}
        QPushButton:checked {{ background: {t['primary']}; color: {t['primary_fg']}; }}
        QPushButton#primary {{ background: {t['primary']}; color: {t['primary_fg']}; border-color: {t['primary']}; font-weight: 600; }}
        QPushButton#primary:hover {{ background: {t['muted_fg']}; border-color: {t['muted_fg']}; }}
        QLabel#title {{ font-size: 18px; font-weight: 700; }}
        QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 6px; top: -1px; }}
        QTabBar::tab {{ background: transparent; color: {t['muted_fg']}; padding: 6px 12px; border-radius: 6px; margin: 2px; }}
        QTabBar::tab:selected {{ background: {t['secondary']}; color: {t['foreground']}; }}
        QTabBar::tab:hover:!selected {{ color: {t['foreground']}; }}
        QHeaderView::section {{ background: {t['muted']}; color: {t['muted_fg']}; border: none; border-bottom: 1px solid {t['border']}; padding: 4px 6px; }}
        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {t['muted_fg']}; border-radius: 4px; background: {t['background']}; }}
        QCheckBox::indicator:checked {{ background: {t['primary']}; border-color: {t['primary']}; image: url({check_icon}); }}
        QCheckBox::indicator:disabled {{ border-color: {t['border']}; }}
        QProgressBar {{ border: 1px solid {t['border']}; border-radius: 6px; text-align: center; background: {t['muted']}; color: {t['foreground']}; }}
        QProgressBar::chunk {{ background: {t['primary']}; border-radius: 5px; }}
        QSplitter::handle {{ background: {t['border']}; }}
        QStatusBar {{ border-top: 1px solid {t['border']}; color: {t['muted_fg']}; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
        QScrollBar::handle {{ background: {t['border']}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
        QScrollBar::handle:hover {{ background: {t['muted_fg']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def apply_theme(window):
    window.dark = getattr(window, "dark", True)
    tokens = THEMES["dark" if window.dark else "light"]
    app = QApplication.instance()
    if app:
        app.setStyle("Fusion")  # ignores QT_STYLE_OVERRIDE / desktop styles so both modes look the same
        app.setPalette(_palette(tokens))
        icon = Path(__file__).parent / "icons" / ("check_dark.svg" if window.dark else "check_light.svg")
        app.setStyleSheet(_stylesheet(tokens, icon.as_posix()))
    window.setStyleSheet("")
    if hasattr(window, "canvas"):
        window.canvas.set_dark_background(window.dark)


def load_settings(window):
    """Restore the theme and the last session (open workspace, or else the last used inputs/options)."""
    settings = window.settings
    window.dark = settings.value("dark", True, type=bool)
    workspace = settings.value("lastWorkspace", "")
    if workspace and Path(workspace).exists():
        try:
            return window.open_workspace_path(workspace, quiet=True)
        except Exception:
            pass
    try:
        state = json.loads(settings.value("session", "") or "{}")
    except Exception:
        state = {}
    if state:
        apply_state(window, state)


def save_settings(window):
    settings = window.settings
    settings.setValue("dark", getattr(window, "dark", True))
    settings.setValue("lastWorkspace", getattr(window, "workspace_path", "") or "")
    settings.setValue("session", json.dumps(collect_state(window)))
