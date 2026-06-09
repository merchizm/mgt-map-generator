import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication, QStyleFactory

from .main_window import MainWindow


def _add_qlementine_plugin_path():
    root = Path(__file__).resolve().parents[2]
    styles_path = root / "build" / "qlementine-style-plugin" / "styles"
    if styles_path.exists():
        QCoreApplication.addLibraryPath(str(styles_path.parent))


def _use_qlementine_style(app):
    _add_qlementine_plugin_path()
    if "Qlementine" in QStyleFactory.keys():
        app.setStyle("Qlementine")
        app.style().setObjectName("QlementineStyle")
        dark = QSettings("MericsGameTools", "MgtMapGenerator").value("dark", True, type=bool)
        app.style().setProperty("darkTheme", dark)
        app.setPalette(app.style().standardPalette())


def main():
    app = QApplication(sys.argv)
    _use_qlementine_style(app)
    app.setApplicationName("Meric's Game Tools - Map Generator")
    app.setApplicationDisplayName("Meric's Game Tools - Map Generator")
    app.setOrganizationName("MericsGameTools")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
