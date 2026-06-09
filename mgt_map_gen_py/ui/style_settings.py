import json

from PySide6.QtWidgets import QApplication

from ..core.geo_utils import DEFAULT_BBOX


def apply_theme(window):
    window.dark = getattr(window, "dark", True)
    app = QApplication.instance()
    if app and app.style() and app.style().objectName().lower() in {"qlementine", "qlementinestyle"}:
        app.style().setProperty("darkTheme", window.dark)
        app.setPalette(app.style().standardPalette())
        window.setStyleSheet("")
        if hasattr(window, "canvas"):
            window.canvas.set_dark_background(window.dark)
        return
    if not window.dark:
        window.setStyleSheet("")
        if hasattr(window, "canvas"):
            window.canvas.set_dark_background(False)
        return
    if hasattr(window, "canvas"):
        window.canvas.set_dark_background(True)
    window.setStyleSheet("""
        QMainWindow, QWidget { background: #0f172a; color: #e5e7eb; font-size: 13px; }
        QGroupBox { border: 1px solid #273449; border-radius: 8px; margin-top: 10px; padding: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #93c5fd; }
        QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox {
            background: #111827; border: 1px solid #334155; border-radius: 6px; padding: 6px; color: #e5e7eb;
        }
        QPushButton { background: #1f2937; border: 1px solid #475569; border-radius: 6px; padding: 7px 10px; }
        QPushButton:hover { background: #263244; }
        QPushButton#primary { background: #0f766e; border-color: #14b8a6; color: white; font-weight: 600; }
        QLabel#title { font-size: 20px; font-weight: 700; color: #f8fafc; }
        QProgressBar { border: 1px solid #334155; border-radius: 6px; text-align: center; background: #111827; }
        QProgressBar::chunk { background: #14b8a6; border-radius: 5px; }
    """)


def load_settings(window):
    settings = window.settings
    window.dark = settings.value("dark", True, type=bool)
    window.out_path.setText(settings.value("outPath", "provinces.geojson"))
    window.package_dir.setText(settings.value("packageDir", ""))
    window.map_key.setText(settings.value("mapKey", ""))
    window.map_name.setText(settings.value("mapName", ""))
    window.map_version.setText(settings.value("mapVersion", ""))
    window.projection.setText(settings.value("projection", "projected-2d"))
    window.use_borders.setChecked(settings.value("useBorders", False, type=bool))
    window.lloyd.setChecked(settings.value("lloyd", False, type=bool))
    window.lloyd_iter.setValue(settings.value("lloydIter", 1, type=int))
    window.river.setChecked(settings.value("river", False, type=bool))
    window.river_strength.setValue(settings.value("riverStrength", 0.32, type=float))
    window.smoothing.setChecked(settings.value("smoothing", False, type=bool))
    window.smoothing_iter.setValue(settings.value("smoothingIter", 1, type=int))
    window.smoothing_strength.setValue(settings.value("smoothingStrength", 0.24, type=float))
    method = settings.value("smoothingMethod", "chaikin")
    index = window.smoothing_method.findText(method)
    if index >= 0:
        window.smoothing_method.setCurrentIndex(index)
    bbox = settings.value("bbox", DEFAULT_BBOX)
    if isinstance(bbox, str):
        try:
            bbox = json.loads(bbox)
        except Exception:
            bbox = DEFAULT_BBOX
    for index, value in enumerate(bbox if isinstance(bbox, list) and len(bbox) == 4 else DEFAULT_BBOX):
        window.bbox_inputs[index].setValue(float(value))


def save_settings(window):
    settings = window.settings
    settings.setValue("dark", getattr(window, "dark", True))
    settings.setValue("outPath", window.out_path.text())
    settings.setValue("packageDir", window.package_dir.text())
    settings.setValue("mapKey", window.map_key.text())
    settings.setValue("mapName", window.map_name.text())
    settings.setValue("mapVersion", window.map_version.text())
    settings.setValue("projection", window.projection.text())
    settings.setValue("useBorders", window.use_borders.isChecked())
    settings.setValue("lloyd", window.lloyd.isChecked())
    settings.setValue("lloydIter", window.lloyd_iter.value())
    settings.setValue("river", window.river.isChecked())
    settings.setValue("riverStrength", window.river_strength.value())
    settings.setValue("smoothing", window.smoothing.isChecked())
    settings.setValue("smoothingMethod", window.smoothing_method.currentText())
    settings.setValue("smoothingIter", window.smoothing_iter.value())
    settings.setValue("smoothingStrength", window.smoothing_strength.value())
    settings.setValue("bbox", json.dumps([spin.value() for spin in window.bbox_inputs]))
