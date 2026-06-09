import traceback

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QStyle, QToolButton, QWidget

from ..core.generator import generate_provinces


class Worker(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, options):
        super().__init__()
        self.options = options

    def run(self):
        try:
            result = generate_provinces({**self.options, "onProgress": self.progress.emit})
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")


class FileRow(QWidget):
    changed = Signal(str, object)

    def __init__(self, key, title, required=False):
        super().__init__()
        self.key = key
        self.path = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        label = QLabel(f"{title}{' *' if required else ''}")
        label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.edit.setPlaceholderText("Required GeoJSON/JSON" if required else "Optional GeoJSON/JSON")

        style = QApplication.style()
        browse = QToolButton()
        browse.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        browse.setIconSize(QSize(18, 18))
        browse.setAutoRaise(True)
        browse.setToolTip(f"Choose {title}")
        clear = QToolButton()
        clear.setIcon(style.standardIcon(QStyle.SP_DialogResetButton))
        clear.setIconSize(QSize(18, 18))
        clear.setAutoRaise(True)
        clear.setToolTip(f"Clear {title}")
        browse.clicked.connect(self.browse)
        clear.clicked.connect(self.clear)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(label)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)
        layout.addWidget(clear)

    def set_path(self, path, notify=True):
        self.path = path or None
        self.edit.setText(path or "")
        if notify:
            self.changed.emit(self.key, self.path)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose GeoJSON",
            "",
            "GeoJSON/JSON (*.geojson *.json);;All Files (*)",
        )
        if path:
            self.set_path(path)

    def clear(self):
        self.set_path(None)
