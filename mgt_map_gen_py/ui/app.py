import sys
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Meric's Game Tools - Map Generator")
    app.setApplicationDisplayName("Meric's Game Tools - Map Generator")
    app.setOrganizationName("MericsGameTools")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
