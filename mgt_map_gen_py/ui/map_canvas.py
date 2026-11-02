from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView, QMenu

from ..core.geo_utils import LAYER_LABELS


# Point layers use a constant on-screen radius (see _draw_feature); line/polygon widths are in screen pixels too.
POINT_RADIUS = {"cities": 3.0, "generatedCities": 3.0, "movementNodes": 2.6, "railNodes": 3.6}

STYLES = {
    "cities": ("#e8bf60", "#ffffff", 4.2),
    "generatedCities": ("#ff8c5c", "#ffffff", 4.2),
    "land": ("#1fa39a40", "#dff5f1", 0.8),
    "lakes": ("#458fff80", "#a9d2ff", 1.0),
    "borders": ("transparent", "#e8bf60", 0.9),
    "oceans": ("#3f7fb650", "#91c4ff", 1.0),
    "seaRegions": ("#4a90e244", "#91c4ff", 1.0),
    "rivers": ("transparent", "#71b1ff", 1.0),
    "movementNodes": ("#ff6ec7", "#ffffff", 4.6),
    "movementEdges": ("transparent", "#ff6ec7", 0.8),
    "railNodes": ("#ffcd56", "#5e4300", 5.0),
    "railEdges": ("transparent", "#ffcd56", 1.2),
    "output": ("#23a79555", "#e7f6f7", 1.0),
    "oceanMask": ("#1d4f7a33", "#7ab8ff", 0.8),
    "lakesMask": ("#458fff60", "#b9d9ff", 0.8),
    "syntheticLakes": ("#458fff70", "#b9d9ff", 0.8),
    "emptyLands": ("#64748b44", "#94a3b8", 0.8),
    "mergedEmptyCountries": ("#f59e0b44", "#fbbf24", 0.9),
}

DRAW_ORDER = {
    "oceans": 0,
    "oceanMask": 1,
    "land": 2,
    "output": 3,
    "seaRegions": 4,
    "lakes": 5,
    "lakesMask": 6,
    "syntheticLakes": 7,
    "emptyLands": 8,
    "mergedEmptyCountries": 9,
    "borders": 10,
    "rivers": 11,
    "movementEdges": 12,
    "railEdges": 13,
    "cities": 14,
    "generatedCities": 15,
    "movementNodes": 16,
    "railNodes": 17,
}


class FeatureItem(QGraphicsPathItem):
    def __init__(self, path, layer_key, feature, canvas):
        super().__init__(path)
        self.layer_key = layer_key
        self.feature = feature
        self.canvas = canvas
        self.base_pen = None
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsPathItem.ItemIsSelectable, True)

    def mousePressEvent(self, event):
        self.canvas.featureSelected.emit({"layer": self.layer_key, "feature": self.feature})
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event):
        self.base_pen = QPen(self.pen())
        pen = self.pen()
        pen.setWidthF(max(1.8, pen.widthF() + 0.8))
        self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if self.base_pen is not None:
            self.setPen(self.base_pen)
        super().hoverLeaveEvent(event)


class MapCanvas(QGraphicsView):
    featureSelected = Signal(dict)
    bboxDrawn = Signal(list)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#111827"))
        self._layers = []
        self._bounds = None
        self._active = "cities"
        self._last_fit_rect = QRectF(0, 0, 960, 640)
        self._draw_bbox_mode = False
        self._bbox_start = None
        self._bbox_item = None
        self._bbox = None
        self._dark_theme = True

    def set_layer(self, layer_key, feature_collection, overlays=None):
        self.set_layers(list(overlays or []) + [(layer_key, feature_collection)], layer_key)

    def set_layers(self, layers, active_layer, bbox=None, keep_view=False):
        self._layers = [
            (key, fc)
            for key, fc in layers
            if isinstance(fc, dict) and fc.get("type") == "FeatureCollection" and fc.get("features")
        ]
        self._layers.sort(key=lambda item: DRAW_ORDER.get(item[0], 50))
        self._active = active_layer
        self._bbox = bbox
        self.redraw(keep_view)

    def zoom_in(self):
        self.scale(1.18, 1.18)

    def zoom_out(self):
        self.scale(0.85, 0.85)

    def set_dark_background(self, enabled):
        self._dark_theme = bool(enabled)
        self.setBackgroundBrush(QColor("#111827" if enabled else "#f8fafc"))

    def set_bbox_draw_mode(self, enabled):
        self._draw_bbox_mode = enabled
        self._bbox_start = None
        self.setDragMode(QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag)

    def reset_view(self):
        # Frame the generation bbox when there is one: that is where the generated provinces are,
        # while the input layers (e.g. a world land mask) can be far larger.
        rect = self._last_fit_rect
        if self._bbox and self._bounds:
            p1 = self._project(self._bbox[0], self._bbox[1])
            p2 = self._project(self._bbox[2], self._bbox[3])
            bbox_rect = QRectF(p1, p2).normalized()
            if bbox_rect.width() > 4 and bbox_rect.height() > 4:
                rect = bbox_rect
        self.fitInView(rect.adjusted(-24, -24, 24, 24), Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        factor = 1.18 if event.angleDelta().y() > 0 else 0.85
        self.scale(factor, factor)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        reset = QAction("Reset View", self)
        reset.triggered.connect(self.reset_view)
        menu.addAction(reset)
        menu.exec(event.globalPos())

    def mousePressEvent(self, event):
        if self._draw_bbox_mode and event.button() == Qt.LeftButton:
            self._bbox_start = self.mapToScene(event.pos())
            if self._bbox_item:
                self.scene().removeItem(self._bbox_item)
                self._bbox_item = None
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._draw_bbox_mode and self._bbox_start is not None:
            end = self.mapToScene(event.pos())
            rect = QRectF(self._bbox_start, end).normalized()
            if self._bbox_item is None:
                pen, brush = self._bbox_style()
                self._bbox_item = self.scene().addRect(
                    rect,
                    pen,
                    brush,
                )
                self._bbox_item.setZValue(120)
            else:
                self._bbox_item.setRect(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._draw_bbox_mode and self._bbox_start is not None and event.button() == Qt.LeftButton:
            end = self.mapToScene(event.pos())
            rect = QRectF(self._bbox_start, end).normalized()
            self._bbox_start = None
            if rect.width() > 6 and rect.height() > 6 and self._bounds:
                a = self._unproject(rect.left(), rect.bottom())
                b = self._unproject(rect.right(), rect.top())
                self._bbox = [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
                self.bboxDrawn.emit(self._bbox)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def redraw(self, keep_view=False):
        scene = self.scene()
        scene.clear()
        bounds = self._compute_bounds()
        if not bounds:
            empty = scene.addText("No preview is available for this layer.")
            empty.setDefaultTextColor(QColor("#cbd5e1"))
            empty.setPos(380, 300)
            scene.setSceneRect(QRectF(0, 0, 1220, 640))
            self._last_fit_rect = QRectF(0, 0, 1220, 640)
            return
        self._bounds = bounds
        self._draw_backdrop()
        scene.setSceneRect(QRectF(0, 0, 1220, 640))
        for layer_key, fc in self._layers:
            for feature in (fc or {}).get("features", []):
                self._draw_feature(layer_key, feature)
        self._draw_bbox()
        self._draw_labels()
        self._draw_legend()
        self._last_fit_rect = scene.itemsBoundingRect()
        if not keep_view:
            self.reset_view()

    def _draw_backdrop(self):
        scene = self.scene()
        scene.addRect(0, 0, 1220, 640, QPen(QColor("#1f2937"), 0), QColor("#0b1220"))
        scene.addRect(0, 0, 960, 640, QPen(QColor("#334155"), 0.8), QColor("#0b1220"))
        for x in range(0, 961, 120):
            scene.addLine(x, 0, x, 640, QPen(QColor("#172033"), 0.5))
        for y in range(0, 641, 80):
            scene.addLine(0, y, 960, y, QPen(QColor("#172033"), 0.5))

    def _compute_bounds(self):
        coords = []
        for _, fc in self._layers:
            for feat in (fc or {}).get("features", []):
                self._collect_coords(feat.get("geometry"), coords)
        if not coords:
            return None
        xs = coords[0::2]
        ys = coords[1::2]
        return min(xs), min(ys), max(xs), max(ys)

    def _collect_coords(self, geom, out):
        if not geom:
            return
        coords = geom.get("coordinates")
        def walk(node):
            if isinstance(node, list) and len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
                out.extend([node[0], node[1]])
            elif isinstance(node, list):
                for child in node:
                    walk(child)
        walk(coords)

    def _project(self, lon, lat):
        minx, miny, maxx, maxy = self._bounds
        width, height, pad = 960, 640, 24
        spanx = max(maxx - minx, 1e-9)
        spany = max(maxy - miny, 1e-9)
        scale = min((width - pad * 2) / spanx, (height - pad * 2) / spany)
        ox = (width - spanx * scale) / 2
        oy = (height - spany * scale) / 2
        return QPointF(ox + (lon - minx) * scale, height - (oy + (lat - miny) * scale))

    def _unproject(self, x, y):
        minx, miny, maxx, maxy = self._bounds
        width, height, pad = 960, 640, 24
        spanx = max(maxx - minx, 1e-9)
        spany = max(maxy - miny, 1e-9)
        scale = min((width - pad * 2) / spanx, (height - pad * 2) / spany)
        ox = (width - spanx * scale) / 2
        oy = (height - spany * scale) / 2
        return ((x - ox) / scale) + minx, ((height - y - oy) / scale) + miny

    def _colors(self, layer_key):
        fill, stroke, width = STYLES.get(layer_key, STYLES.get("output"))
        return QColor(fill) if fill != "transparent" else Qt.NoBrush, QColor(stroke), width

    def _draw_feature(self, layer_key, feat):
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        fill, stroke, stroke_width = self._colors(layer_key)
        if layer_key == self._active:
            stroke_width += 0.45
        if gtype == "Point":
            radius = POINT_RADIUS.get(layer_key, 3.0) + (0.6 if layer_key == self._active else 0)
            path = QPainterPath()
            path.addEllipse(QPointF(0, 0), radius, radius)
            item = self._add_item(path, layer_key, feat, QPen(stroke, 0.8), QColor(fill) if fill != Qt.NoBrush else stroke)
            # Marker keeps its pixel size at every zoom level; only its position follows the map.
            item.setFlag(QGraphicsPathItem.ItemIgnoresTransformations, True)
            item.setPos(self._project(coords[0], coords[1]))
            return
        if gtype in ("LineString", "MultiLineString"):
            lines = [coords] if gtype == "LineString" else coords
            for line in lines:
                path = QPainterPath()
                for index, point in enumerate(line):
                    p = self._project(point[0], point[1])
                    path.moveTo(p) if index == 0 else path.lineTo(p)
                self._add_item(path, layer_key, feat, QPen(stroke, stroke_width), Qt.NoBrush)
            return
        if gtype in ("Polygon", "MultiPolygon"):
            polygons = [coords] if gtype == "Polygon" else coords
            for polygon in polygons:
                path = QPainterPath()
                for ring in polygon:
                    for index, point in enumerate(ring):
                        p = self._project(point[0], point[1])
                        path.moveTo(p) if index == 0 else path.lineTo(p)
                    path.closeSubpath()
                self._add_item(path, layer_key, feat, QPen(stroke, stroke_width), fill)

    def _add_item(self, path, layer_key, feat, pen, brush):
        item = FeatureItem(path, layer_key, feat, self)
        pen = QPen(pen)
        pen.setCosmetic(True)  # constant pixel width regardless of zoom
        item.setPen(pen)
        item.setBrush(brush)
        item.setToolTip(self._tooltip(layer_key, feat))
        item.setZValue(DRAW_ORDER.get(layer_key, 50))
        self.scene().addItem(item)
        return item

    def _bbox_style(self):
        if self._dark_theme:
            base = QColor("#5eead4")
        else:
            base = QColor("#0f766e")
        fill = QColor(base)
        fill.setAlphaF(0.15)
        pen = QPen(base, 1.5, Qt.DashLine)
        return pen, QBrush(fill)

    def _draw_bbox(self):
        if not self._bbox or not self._bounds:
            return
        min_lng, min_lat, max_lng, max_lat = self._bbox
        p1 = self._project(min_lng, min_lat)
        p2 = self._project(max_lng, max_lat)
        pen, brush = self._bbox_style()
        item = self.scene().addRect(
            QRectF(p1, p2).normalized(),
            pen,
            brush,
        )
        item.setZValue(119)

    def _draw_labels(self):
        active = next((fc for key, fc in self._layers if key == self._active), None)
        features = (active or {}).get("features", [])
        if len(features) > 180:
            return
        font = QFont()
        font.setPointSize(8)
        for feat in features:
            props = feat.get("properties") or {}
            name = props.get("name")
            geom = feat.get("geometry") or {}
            if not name or geom.get("type") != "Point":
                continue
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue
            p = self._project(coords[0], coords[1])
            text = QGraphicsTextItem(str(name))
            text.setFont(font)
            text.setDefaultTextColor(QColor("#e5e7eb"))
            text.setPos(p.x() + 6, p.y() - 14)
            text.setFlag(QGraphicsTextItem.ItemIgnoresTransformations, True)
            text.setZValue(90)
            self.scene().addItem(text)

    def _draw_legend(self):
        x, y = 990, 22
        bg = self.scene().addRect(x - 10, y - 10, 210, 30 + len(self._layers) * 20, QPen(QColor("#334155"), 0.8), QColor("#0f172acc"))
        bg.setZValue(100)
        title = self.scene().addText("Preview Layers")
        title.setDefaultTextColor(QColor("#f8fafc"))
        title.setPos(x, y - 6)
        title.setZValue(101)
        for index, (layer_key, fc) in enumerate(self._layers):
            yy = y + 24 + index * 20
            fill, stroke, _ = self._colors(layer_key)
            swatch = self.scene().addRect(x, yy + 4, 12, 8, QPen(stroke, 1), fill if fill != Qt.NoBrush else QColor("#0f172a"))
            swatch.setZValue(101)
            label = self.scene().addText(f"{LAYER_LABELS.get(layer_key, layer_key)} ({len(fc.get('features', []))})")
            label.setDefaultTextColor(QColor("#cbd5e1" if layer_key != self._active else "#ffffff"))
            label.setPos(x + 18, yy - 2)
            label.setZValue(101)

    def _tooltip(self, layer_key, feat):
        props = feat.get("properties") or {}
        name = props.get("name") or props.get("key") or LAYER_LABELS.get(layer_key, layer_key)
        country = props.get("country")
        return f"{name}" + (f"\n{country}" if country else "")
