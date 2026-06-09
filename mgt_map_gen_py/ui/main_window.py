from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QMenu,
    QStyle,
    QToolButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..core.generator import DEFAULT_INPUTS, zip_package
from ..core.geo_utils import DEFAULT_BBOX, EMPTY_COUNTRY_POLICIES, LAYER_LABELS, LAYER_ORDER, country_display_name, get_border_aliases, normalize_value, read_json
from .widgets import FileRow, Worker
from .map_canvas import MapCanvas
from .style_settings import apply_theme, load_settings, save_settings


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Meric's Game Tools - Map Generator")
        self.resize(1500, 920)
        self.files = {}
        self.layers = {}
        self.active_layer = "cities"
        self.result = None
        self.empty_overrides = {}
        self.thread = None
        self.worker = None
        self.current_job_mode = None
        self.ignore_current_live_result = False
        self.live_output_dirs = set()
        self.live_preview_enabled = False
        self.live_timer = QTimer(self)
        self.live_timer.setSingleShot(True)
        self.live_timer.setInterval(1800)
        self.live_timer.timeout.connect(self.run_live_preview)
        self.settings = QSettings("MericsGameTools", "MgtMapGenerator")
        self._build_actions()
        self._build_ui()
        load_settings(self)
        self._connect_live_triggers()
        apply_theme(self)

    def _build_actions(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("File")
        new_action = QAction("New", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.new_project)
        open_action = QAction("Open Layer", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(lambda: self.file_rows["cities"].browse())
        generate_action = QAction("Run", self)
        generate_action.setShortcut("Ctrl+R")
        generate_action.triggered.connect(lambda: self.generate("manual"))
        export_action = QAction("Export Package as Zip", self)
        export_action.triggered.connect(self.export_zip)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        for action in [new_action, open_action, generate_action, export_action, quit_action]:
            file_menu.addAction(action)

        view_menu = menu.addMenu("View")
        theme_action = QAction("Toggle Theme", self)
        theme_action.triggered.connect(self.toggle_theme)
        reset_view = QAction("Reset Map View", self)
        reset_view.triggered.connect(lambda: self.canvas.reset_view())
        view_menu.addAction(theme_action)
        view_menu.addAction(reset_view)

        help_menu = menu.addMenu("Help")
        help_action = QAction("How to Use", self)
        help_action.triggered.connect(self.show_help_dialog)
        about_action = QAction("About Meric's Game Tools - Map Generator", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(help_action)
        help_menu.addAction(about_action)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(new_action)
        toolbar.addAction(open_action)
        toolbar.addAction(generate_action)
        toolbar.addAction(export_action)
        toolbar.addAction(reset_view)

    def _build_ui(self):
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setWidget(self._left_panel())
        splitter.addWidget(left_scroll)
        splitter.addWidget(self._center_panel())
        splitter.addWidget(self._right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")

    def _left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        title = QLabel("Meric's Game Tools - Map Generator")
        title.setObjectName("title")
        layout.addWidget(title)

        control_tabs = QTabWidget()
        control_tabs.setDocumentMode(True)
        layout.addWidget(control_tabs, 1)

        setup_page = QWidget()
        setup_layout = QVBoxLayout(setup_page)
        control_tabs.addTab(setup_page, "Setup")

        generation_page = QWidget()
        generation_layout = QVBoxLayout(generation_page)
        control_tabs.addTab(generation_page, "Generation")

        self.file_rows = {}
        data = QGroupBox("Data Setup")
        data_layout = QVBoxLayout(data)
        data_layout.setSpacing(10)
        specs = [
            ("cities", "Cities", True),
            ("seaCities", "Sea Seeds", False),
            ("land", "Land Mask", True),
            ("oceans", "Oceans", False),
            ("lakes", "Lakes", False),
            ("rivers", "Rivers", False),
            ("borders", "Borders", False),
        ]
        for key, label, required in specs:
            row = FileRow(key, label, required)
            row.changed.connect(self.load_layer_file)
            self.file_rows[key] = row
            data_layout.addWidget(row)
        self.use_borders = QCheckBox("Use Borders")
        data_layout.addWidget(self.use_borders)
        self.out_path = QLineEdit("provinces.geojson")
        self.out_path.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        data_layout.addWidget(QLabel("Output File"))
        data_layout.addWidget(self.out_path)
        setup_layout.addWidget(data)
        package_button = QPushButton("Package Settings")
        package_button.clicked.connect(self.open_package_dialog)
        setup_layout.addWidget(package_button)
        setup_layout.addStretch(1)

        gen = QGroupBox("Generation Controls")
        form = QFormLayout(gen)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.lloyd = QCheckBox()
        self.lloyd_iter = QSpinBox()
        self.lloyd_iter.setRange(1, 4)
        self.lloyd_iter.setValue(1)
        self.river = QCheckBox()
        self.river_strength = QDoubleSpinBox()
        self.river_strength.setRange(0, 1)
        self.river_strength.setSingleStep(0.01)
        self.river_strength.setValue(0.32)
        self.smoothing = QCheckBox()
        self.smoothing_method = QComboBox()
        self.smoothing_method.addItems(["chaikin", "bezier"])
        self.smoothing_iter = QSpinBox()
        self.smoothing_iter.setRange(1, 4)
        self.smoothing_strength = QDoubleSpinBox()
        self.smoothing_strength.setRange(0.05, 0.45)
        self.smoothing_strength.setSingleStep(0.01)
        self.smoothing_strength.setValue(0.24)
        self.policy_default = QComboBox()
        self.policy_default.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.policy_default.addItem("Keep Empty Land", EMPTY_COUNTRY_POLICIES["empty"])
        self.policy_default.addItem("Convert to Lake", EMPTY_COUNTRY_POLICIES["lake"])
        self.policy_default.addItem("Merge to Nearest Small Land", EMPTY_COUNTRY_POLICIES["merge"])
        form.addRow("Lloyd", self.lloyd)
        form.addRow("Iterations", self.lloyd_iter)
        form.addRow("River Influence", self.river)
        form.addRow("River Strength", self.river_strength)
        form.addRow("Edge Smoothing", self.smoothing)
        form.addRow("Method", self.smoothing_method)
        form.addRow("Smooth Iter.", self.smoothing_iter)
        form.addRow("Strength", self.smoothing_strength)
        form.addRow("Empty Country", self.policy_default)
        generation_layout.addWidget(gen)

        package = QGroupBox("Package Metadata")
        self.package_panel = QWidget()
        package_layout = QVBoxLayout(self.package_panel)
        package_form = QGridLayout(package)
        package_form.setHorizontalSpacing(8)
        package_form.setVerticalSpacing(6)
        self.map_key = QLineEdit()
        self.map_name = QLineEdit()
        self.map_version = QLineEdit()
        self.projection = QLineEdit("projected-2d")
        for widget in [self.map_key, self.map_name, self.map_version, self.projection]:
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.world_width = QDoubleSpinBox()
        self.world_width.setRange(0, 1000000)
        self.world_width.setDecimals(3)
        self.world_height = QDoubleSpinBox()
        self.world_height.setRange(0, 1000000)
        self.world_height.setDecimals(3)
        self.package_dir = QLineEdit()
        self.package_dir.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        package_browse = QToolButton()
        package_browse.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        package_browse.setIconSize(QSize(18, 18))
        package_browse.setToolTip("Choose package folder")
        package_browse.clicked.connect(self.browse_package_dir)
        package_row = QHBoxLayout()
        package_row.setContentsMargins(0, 0, 0, 0)
        package_row.addWidget(self.package_dir, 1)
        package_row.addWidget(package_browse)
        package_form.addWidget(QLabel("Map Key"), 0, 0)
        package_form.addWidget(self.map_key, 0, 1)
        package_form.addWidget(QLabel("Version"), 0, 2)
        package_form.addWidget(self.map_version, 0, 3)
        package_form.addWidget(QLabel("Map Name"), 1, 0)
        package_form.addWidget(self.map_name, 1, 1, 1, 3)
        package_form.addWidget(QLabel("Projection"), 2, 0)
        package_form.addWidget(self.projection, 2, 1)
        package_form.addWidget(QLabel("Width"), 2, 2)
        package_form.addWidget(self.world_width, 2, 3)
        package_form.addWidget(QLabel("Height"), 3, 2)
        package_form.addWidget(self.world_height, 3, 3)
        package_form.addWidget(QLabel("Package Dir"), 3, 0)
        package_form.addLayout(package_row, 3, 1)
        package_form.setColumnStretch(1, 1)
        package_form.setColumnStretch(3, 1)
        package_layout.addWidget(package)
        package_layout.addStretch(1)

        bbox = QGroupBox("BBox")
        bbox_layout = QGridLayout(bbox)
        self.bbox_inputs = []
        for index, label in enumerate(["Min Lng", "Min Lat", "Max Lng", "Max Lat"]):
            spin = QDoubleSpinBox()
            spin.setRange(-360, 360)
            spin.setDecimals(6)
            spin.setValue(DEFAULT_BBOX[index])
            self.bbox_inputs.append(spin)
            bbox_layout.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            bbox_layout.addWidget(spin, index // 2, (index % 2) * 2 + 1)
        generation_layout.addWidget(bbox)
        generation_layout.addStretch(1)
        btns = QHBoxLayout()
        analyze = QPushButton("Analyze Empty Countries")
        analyze.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        analyze.clicked.connect(self.analyze_empty_countries)
        generate = QPushButton("Run")
        generate.setObjectName("primary")
        generate.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        generate.clicked.connect(lambda: self.generate("manual"))
        live_menu = QMenu(self)
        live_start = QAction("Process Live Preview", self)
        live_start.triggered.connect(self.start_live_preview)
        live_stop = QAction("Stop Live Processing", self)
        live_stop.triggered.connect(self.stop_live_preview)
        live_menu.addAction(live_start)
        live_menu.addAction(live_stop)
        live_button = QToolButton()
        live_button.setText("▾")
        live_button.setPopupMode(QToolButton.InstantPopup)
        live_button.setMenu(live_menu)
        live_button.setToolTip("Live processing options")
        btns.addWidget(analyze)
        btns.addWidget(generate)
        btns.addWidget(live_button)
        layout.addLayout(btns)
        return panel

    def browse_package_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Package Directory")
        if path:
            self.package_dir.setText(path)

    def open_package_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Package Settings")
        layout = QVBoxLayout(dialog)
        self.package_panel.setParent(dialog)
        layout.addWidget(self.package_panel)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        dialog.exec()
        self.package_panel.setParent(None)

    def _center_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        header = QHBoxLayout()
        self.status_label = QLabel("idle")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.view_tabs = QTabWidget()
        self.canvas = MapCanvas()
        self.canvas.featureSelected.connect(self.on_feature_selected)
        self.code = QPlainTextEdit()
        self.code.setReadOnly(True)
        self.canvas.bboxDrawn.connect(self.on_bbox_drawn)
        self.view_tabs.addTab(self.canvas, "Map")
        self.view_tabs.addTab(self.code, "Code")
        copy = QPushButton("Copy Code")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.code.toPlainText()))
        zoom_in = QPushButton("+")
        zoom_in.setToolTip("Zoom in")
        zoom_in.clicked.connect(self.canvas.zoom_in)
        zoom_out = QPushButton("-")
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(self.canvas.zoom_out)
        self.draw_bbox_button = QPushButton("Draw BBox")
        self.draw_bbox_button.setCheckable(True)
        self.draw_bbox_button.clicked.connect(self.toggle_bbox_draw)
        reset = QPushButton("Reset View")
        reset.clicked.connect(self.canvas.reset_view)
        header.addWidget(self.status_label)
        header.addWidget(self.progress, 1)
        header.addWidget(copy)
        header.addWidget(zoom_out)
        header.addWidget(zoom_in)
        header.addWidget(self.draw_bbox_button)
        header.addWidget(reset)
        layout.addLayout(header)
        layout.addWidget(self.view_tabs, 1)
        self.bottom_tabs = QTabWidget()
        self.layer_list = QListWidget()
        self.layer_list.itemSelectionChanged.connect(self.select_layer_from_list)
        self.package_text = QTextEdit()
        self.package_text.setReadOnly(True)
        self.warning_text = QTextEdit()
        self.warning_text.setReadOnly(True)
        self.diagnostic_text = QTextEdit()
        self.diagnostic_text.setReadOnly(True)
        self.bottom_tabs.addTab(self.layer_list, "Layers")
        self.bottom_tabs.addTab(self.package_text, "Package")
        self.bottom_tabs.addTab(self.warning_text, "Warnings")
        self.bottom_tabs.addTab(self.diagnostic_text, "Diagnostics")
        layout.addWidget(self.bottom_tabs, 0)
        return panel

    def _right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        title = QLabel("Inspector")
        title.setObjectName("title")
        self.inspector = QTextEdit()
        self.inspector.setReadOnly(True)
        self.empty_list = QListWidget()
        policies = QPushButton("Empty Country Policies")
        policies.clicked.connect(self.open_policy_dialog)
        layout.addWidget(title)
        layout.addWidget(self.inspector, 1)
        layout.addWidget(QLabel("Empty Countries"))
        layout.addWidget(self.empty_list, 1)
        layout.addWidget(policies)
        return panel

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About Meric's Game Tools - Map Generator")
        layout = QVBoxLayout(dialog)

        title = QLabel("Meric's Game Tools - Map Generator")
        title.setObjectName("title")
        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            body.setMaximumSize(int(available.width() * 0.7), int(available.height() * 0.7))
        body.setHtml(
            """
            <p><b>Meric's Game Tools - Map Generator</b> is a desktop workbench for building Meric's Game Tools map packages.</p>
            <p>It imports GeoJSON source layers, generates provinces and sea regions, builds movement and rail graph outputs, and lets you inspect the generated layers before export.</p>
            <p><b>Repository:</b><br>
            <a href="https://github.com/merchizm/mgt_map_generator">https://github.com/merchizm/mgt_map_generator</a></p>
            """
        )
        buttons = QHBoxLayout()
        help_button = QPushButton("Help")
        help_button.clicked.connect(self.show_help_dialog)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(help_button)
        buttons.addWidget(close_button)

        layout.addWidget(title)
        layout.addWidget(body, 1)
        layout.addLayout(buttons)
        dialog.exec()

    def show_help_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("How to Use Meric's Game Tools - Map Generator")
        layout = QVBoxLayout(dialog)
        help_text = QTextBrowser()
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            help_text.setMaximumSize(int(available.width() * 0.7), int(available.height() * 0.7))
        help_text.setHtml(
            """
            <h2>How to Use</h2>
            <ol>
              <li><b>Add required layers.</b> Choose <code>Cities</code> and <code>Land Mask</code>. These are required before generation can run.</li>
              <li><b>Add optional layers.</b> Add lakes, rivers, borders, oceans, and sea seeds when your map needs them. Sea seeds require an oceans polygon layer. Border mode requires a borders file.</li>
              <li><b>Set the bbox.</b> Edit the numeric bbox fields, or click <b>Draw BBox</b> and drag directly on the preview map.</li>
              <li><b>Adjust generation controls.</b> Enable Lloyd relaxation, river influence, edge smoothing, and empty-country policies as needed.</li>
              <li><b>Preview layers.</b> Select layers from the Layers tab. The map preview shows reference overlays, a legend, and clickable features.</li>
              <li><b>Run generation.</b> Click <b>Run</b> to generate the output package. Use the dropdown next to Run to enable or stop debounced live preview processing.</li>
              <li><b>Inspect output.</b> Review Package, Warnings, and Diagnostics tabs. Click map features to inspect their properties.</li>
              <li><b>Export.</b> Use <b>Export Package as Zip</b> after generation completes.</li>
            </ol>
            <h3>Live Preview</h3>
            <p>Live preview starts only after all required layers are present. It is debounced and will not start a new worker while another one is running.</p>
            """
        )
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(help_text, 1)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        dialog.exec()

    def toggle_theme(self):
        self.dark = not getattr(self, "dark", True)
        apply_theme(self)
        self.settings.setValue("dark", self.dark)

    def closeEvent(self, event):
        save_settings(self)
        self.cleanup_live_output_dirs()
        super().closeEvent(event)

    def _connect_live_triggers(self):
        for widget in [
            self.use_borders,
            self.lloyd,
            self.river,
            self.smoothing,
        ]:
            widget.toggled.connect(self.schedule_live_preview)
        for widget in [
            self.lloyd_iter,
            self.river_strength,
            self.smoothing_iter,
            self.smoothing_strength,
            *self.bbox_inputs,
        ]:
            widget.valueChanged.connect(self.schedule_live_preview)
        for widget in [
            self.smoothing_method,
            self.policy_default,
        ]:
            widget.currentIndexChanged.connect(self.schedule_live_preview)
        for widget in [
            self.out_path,
            self.map_key,
            self.map_name,
            self.map_version,
            self.projection,
            self.package_dir,
        ]:
            widget.textChanged.connect(self.schedule_live_preview)

    def start_live_preview(self):
        self.live_preview_enabled = True
        self.ignore_current_live_result = False
        self.statusBar().showMessage("Live preview is enabled.")
        self.schedule_live_preview()

    def stop_live_preview(self):
        self.live_preview_enabled = False
        self.live_timer.stop()
        if self.current_job_mode == "live":
            self.ignore_current_live_result = True
        self.statusBar().showMessage("Live processing stopped.")

    def schedule_live_preview(self, *_):
        if not getattr(self, "live_preview_enabled", False):
            return
        if not self.has_required_layers():
            self.statusBar().showMessage("Live preview is waiting for required layers.")
            return
        if self.thread and self.thread.isRunning():
            return
        self.live_timer.start()

    def run_live_preview(self):
        if self.live_preview_enabled and self.has_required_layers():
            self.generate("live")

    def has_required_layers(self):
        if not self.files.get("cities") or not self.files.get("land"):
            return False
        if self.files.get("seaCities") and not self.files.get("oceans"):
            return False
        if self.use_borders.isChecked() and not self.files.get("borders"):
            return False
        return True

    def new_project(self):
        self.files.clear()
        self.layers.clear()
        self.result = None
        self.cleanup_live_output_dirs()
        for row in self.file_rows.values():
            row.clear()
        self.layer_list.clear()
        self.code.clear()
        self.package_text.clear()
        self.warning_text.clear()
        self.diagnostic_text.clear()
        self.status_label.setText("idle")
        self.progress.setValue(0)
        self.update_preview()

    def load_layer_file(self, key, path):
        if not path:
            self.files.pop(key, None)
            self.layers.pop(key, None)
        else:
            self.files[key] = path
            try:
                self.layers[key] = read_json(path)
                self.active_layer = key
            except Exception as exc:
                QMessageBox.warning(self, "Could Not Read File", str(exc))
        self.refresh_layers()
        self.update_preview()
        self.schedule_live_preview()

    def refresh_layers(self):
        self.layer_list.clear()
        for key in LAYER_ORDER:
            layer = self.layers.get(key)
            count = len(layer.get("features", [])) if isinstance(layer, dict) and layer.get("type") == "FeatureCollection" else 0
            if count:
                self.layer_list.addItem(f"{LAYER_LABELS.get(key, key)}  ({count})")

    def select_layer_from_list(self):
        text = self.layer_list.currentItem().text() if self.layer_list.currentItem() else ""
        for key in LAYER_ORDER:
            if text.startswith(LAYER_LABELS.get(key, key)):
                self.active_layer = key
                self.update_preview()
                return

    def update_preview(self):
        layer = self.layers.get(self.active_layer)
        preview_layers = self.preview_layer_stack(self.active_layer)
        self.canvas.set_layers(preview_layers, self.active_layer, [spin.value() for spin in self.bbox_inputs])
        self.code.setPlainText(json.dumps(layer or {}, ensure_ascii=False, indent=2))
        self.update_inspector()

    def toggle_bbox_draw(self, checked):
        self.canvas.set_bbox_draw_mode(checked)
        self.statusBar().showMessage("Drag on the map to draw a bounding box." if checked else "BBox drawing disabled.")

    def on_bbox_drawn(self, bbox):
        for index, value in enumerate(bbox):
            self.bbox_inputs[index].blockSignals(True)
            self.bbox_inputs[index].setValue(value)
            self.bbox_inputs[index].blockSignals(False)
        self.draw_bbox_button.setChecked(False)
        self.canvas.set_bbox_draw_mode(False)
        self.update_preview()
        self.schedule_live_preview()
        self.statusBar().showMessage("BBox updated from map preview.")

    def preview_layer_stack(self, active_layer):
        stack = []
        for key in ["oceans", "oceanMask", "land"]:
            if key != active_layer and self.layers.get(key):
                stack.append((key, self.layers[key]))
        if active_layer != "lakes" and self.layers.get("lakes"):
            stack.append(("lakes", self.layers["lakes"]))
        if active_layer != "borders" and self.layers.get("borders"):
            stack.append(("borders", self.layers["borders"]))
        if self.layers.get(active_layer):
            stack.append((active_layer, self.layers[active_layer]))
        if active_layer == "output":
            for key in ["rivers", "movementEdges", "railEdges", "movementNodes", "railNodes", "generatedCities"]:
                if self.layers.get(key):
                    stack.append((key, self.layers[key]))
        elif active_layer not in {"rivers", "movementEdges", "railEdges"} and self.layers.get("rivers"):
            stack.append(("rivers", self.layers["rivers"]))
        return stack

    def on_feature_selected(self, payload):
        feature = payload.get("feature") or {}
        props = feature.get("properties") or {}
        details = [
            "Selected Feature",
            f"Layer: {LAYER_LABELS.get(payload.get('layer'), payload.get('layer'))}",
            f"Geometry: {(feature.get('geometry') or {}).get('type', '-')}",
        ]
        for key in ["name", "key", "country", "regionType", "main_city", "edgeType", "distance"]:
            if key in props:
                details.append(f"{key}: {props[key]}")
        self.statusBar().showMessage(" | ".join(details[:4]))
        self.inspector.setPlainText(self.inspector.toPlainText() + "\n\n" + "\n".join(details))

    def update_inspector(self):
        layer = self.layers.get(self.active_layer) or {}
        lines = [
            f"Status: {self.status_label.text()}",
            f"Selected Layer: {LAYER_LABELS.get(self.active_layer, self.active_layer)}",
            f"Feature: {len(layer.get('features', [])) if isinstance(layer, dict) else 0}",
            f"Borders: {'On' if self.use_borders.isChecked() else 'Off'}",
            f"Lloyd: {self.lloyd_iter.value()}x" if self.lloyd.isChecked() else "Lloyd: Off",
            f"Smoothing: {self.smoothing_method.currentText()}" if self.smoothing.isChecked() else "Smoothing: Off",
            f"Live Preview: {'On' if self.live_preview_enabled else 'Off'}",
        ]
        if self.result:
            meta = self.result.get("package", {}).get("metadata", {})
            lines.extend(["", f"Package Key: {meta.get('key', '-')}", f"Version: {meta.get('version', '-')}", f"Regions: {self.result.get('featureCount', '-')}"])
        self.inspector.setPlainText("\n".join(lines))

    def analyze_empty_countries(self):
        self.empty_list.clear()
        self.empty_countries = []
        if not self.use_borders.isChecked() or not self.layers.get("cities") or not self.layers.get("borders"):
            return
        represented = set()
        for feat in self.layers["cities"].get("features", []):
            props = feat.get("properties") or {}
            for value in [props.get("country"), props.get("COUNTRY"), props.get("iso_a2"), props.get("iso_a3")]:
                key = normalize_value(value)
                if key:
                    represented.add(key)
        for feat in self.layers["borders"].get("features", []):
            props = feat.get("properties") or {}
            aliases = get_border_aliases(props)
            if any(alias in represented for alias in aliases):
                continue
            name = country_display_name(props)
            key = normalize_value(name)
            if key and not any(item["key"] == key for item in self.empty_countries):
                self.empty_countries.append({"key": key, "name": name})
        self.empty_countries.sort(key=lambda x: x["name"])
        for item in self.empty_countries:
            self.empty_list.addItem(f"{item['name']}  [{self.empty_overrides.get(item['key'], self.policy_default.currentData())}]")

    def open_policy_dialog(self):
        self.analyze_empty_countries()
        dialog = QDialog(self)
        dialog.setWindowTitle("Empty Country Policies")
        layout = QVBoxLayout(dialog)
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Country", "Policy"])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        combos = {}
        countries = getattr(self, "empty_countries", [])
        table.setRowCount(max(1, len(countries)))
        policy_labels = ["Use Default", "Keep Empty Land", "Convert to Lake", "Merge to Nearest Small Land"]
        policy_width = max(table.fontMetrics().horizontalAdvance(label) for label in policy_labels) + 56
        for row_index, country in enumerate(countries):
            combo = QComboBox()
            combo.addItem("Use Default", "")
            combo.addItem("Keep Empty Land", EMPTY_COUNTRY_POLICIES["empty"])
            combo.addItem("Convert to Lake", EMPTY_COUNTRY_POLICIES["lake"])
            combo.addItem("Merge to Nearest Small Land", EMPTY_COUNTRY_POLICIES["merge"])
            combo.setMinimumContentsLength(12)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            override_index = combo.findData(self.empty_overrides.get(country["key"], ""))
            combo.setCurrentIndex(override_index if override_index >= 0 else 0)
            combos[country["key"]] = combo
            table.setItem(row_index, 0, QTableWidgetItem(country["name"]))
            table.setCellWidget(row_index, 1, combo)
        if not countries:
            table.setItem(0, 0, QTableWidgetItem("No empty countries detected."))
            table.setSpan(0, 0, 1, 2)
        table.resizeRowsToContents()
        table.setColumnWidth(1, policy_width)
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            table.setMaximumSize(int(available.width() * 0.6), int(available.height() * 0.7))
        layout.addWidget(table, 1)
        save = QPushButton("Save")
        save.clicked.connect(dialog.accept)
        layout.addWidget(save, 0, Qt.AlignRight)
        if dialog.exec():
            self.empty_overrides = {key: combo.currentData() for key, combo in combos.items() if combo.currentData()}
            self.analyze_empty_countries()

    def options(self):
        return {
            "citiesPath": self.files.get("cities"),
            "seaCitiesPath": self.files.get("seaCities"),
            "landPath": self.files.get("land"),
            "lakesPath": self.files.get("lakes"),
            "bordersPath": self.files.get("borders"),
            "oceansPath": self.files.get("oceans"),
            "riversPath": self.files.get("rivers"),
            "outPath": self.out_path.text().strip() or DEFAULT_INPUTS["out"],
            "bbox": [spin.value() for spin in self.bbox_inputs],
            "useBorders": self.use_borders.isChecked(),
            "emptyCountryPolicyDefault": self.policy_default.currentData(),
            "emptyCountryOverrides": self.empty_overrides,
            "lloydEnabled": self.lloyd.isChecked(),
            "lloydIterations": self.lloyd_iter.value(),
            "riverInfluenceEnabled": self.river.isChecked(),
            "riverInfluenceStrength": self.river_strength.value(),
            "smoothingEnabled": self.smoothing.isChecked(),
            "smoothingMethod": self.smoothing_method.currentText(),
            "smoothingIterations": self.smoothing_iter.value(),
            "smoothingStrength": self.smoothing_strength.value(),
            "mapKey": self.map_key.text().strip() or None,
            "mapName": self.map_name.text().strip() or None,
            "mapVersion": self.map_version.text().strip() or None,
            "projection": self.projection.text().strip() or None,
            "worldWidth": self.world_width.value() or None,
            "worldHeight": self.world_height.value() or None,
            "packageDir": self.package_dir.text().strip() or None,
        }

    def generate(self, mode="manual"):
        opts = self.options()
        if not opts["citiesPath"] or not opts["landPath"]:
            if mode == "manual":
                QMessageBox.warning(self, "Missing Data", "Cities and land files are required.")
            return
        if opts["seaCitiesPath"] and not opts["oceansPath"]:
            if mode == "manual":
                QMessageBox.warning(self, "Missing Data", "An oceans polygon must be selected when sea seeds are selected.")
            return
        if opts["useBorders"] and not opts["bordersPath"]:
            if mode == "manual":
                QMessageBox.warning(self, "Missing Data", "A borders file must be selected when border mode is enabled.")
            return
        if self.thread and self.thread.isRunning():
            return
        if mode == "live":
            live_dir = Path(tempfile.mkdtemp(prefix="mgt-map-live-"))
            opts["outPath"] = str(live_dir / "provinces.geojson")
            opts["packageDir"] = str(live_dir)
            opts["livePreview"] = True
            opts["livePreviewOutputDir"] = str(live_dir)
            self.live_output_dirs.add(str(live_dir))
        self.current_job_mode = mode
        self.ignore_current_live_result = False
        self.status_label.setText("running")
        self.progress.setValue(0)
        self.thread = QThread()
        self.worker = Worker(opts)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.start()

    def on_progress(self, progress):
        self.progress.setValue(progress.get("percent", 0))
        self.status_label.setText(progress.get("stage", "running"))
        self.statusBar().showMessage(progress.get("detail", ""))
        self.update_inspector()

    def on_finished(self, result):
        self.status_label.setText("completed")
        self.progress.setValue(100)
        if self.current_job_mode == "live" and self.ignore_current_live_result:
            self.ignore_current_live_result = False
            self.current_job_mode = None
            self.cleanup_live_output_dirs(keep=self.live_result_output_dir(self.result))
            self.statusBar().showMessage("Ignored stopped live preview result.")
            return
        self.result = result
        self.layers["output"] = result["output"]
        for key, value in result.get("layers", {}).items():
            self.layers[key] = value
        self.active_layer = "output"
        self.refresh_layers()
        self.update_preview()
        self.package_text.setPlainText(json.dumps(result.get("package", {}), ensure_ascii=False, indent=2))
        self.warning_text.setPlainText(json.dumps(result.get("warnings", []), ensure_ascii=False, indent=2))
        self.diagnostic_text.setPlainText(json.dumps(result.get("diagnostics", {}), ensure_ascii=False, indent=2))
        self.current_job_mode = None
        self.cleanup_live_output_dirs(keep=self.live_result_output_dir(result))
        self.statusBar().showMessage("Output is ready")
        if self.live_preview_enabled:
            self.schedule_live_preview()

    def on_failed(self, message):
        self.status_label.setText("failed")
        self.warning_text.setPlainText(message)
        self.cleanup_live_output_dirs(keep=self.live_result_output_dir(self.result))
        self.current_job_mode = None
        QMessageBox.critical(self, "Generation Failed", message.splitlines()[0])

    def live_result_output_dir(self, result):
        paths = (result or {}).get("package", {}).get("paths", {})
        package_dir = paths.get("dir")
        if not package_dir:
            return None
        resolved = str(Path(package_dir).resolve())
        if resolved in {str(Path(path).resolve()) for path in self.live_output_dirs}:
            return resolved
        return None

    def cleanup_live_output_dirs(self, keep=None):
        keep = str(Path(keep).resolve()) if keep else None
        remaining = set()
        for path in self.live_output_dirs:
            resolved = str(Path(path).resolve())
            if keep and resolved == keep:
                remaining.add(resolved)
                continue
            shutil.rmtree(resolved, ignore_errors=True)
        self.live_output_dirs = remaining

    def export_zip(self):
        if not self.result:
            QMessageBox.information(self, "No Package", "Generation must complete before exporting.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Zip", "map-package.zip", "Zip (*.zip)")
        if path:
            zip_package(self.result["package"]["paths"], path)
            self.statusBar().showMessage(f"Zip written: {path}")
