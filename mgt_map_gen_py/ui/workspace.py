"""Workspace state: the input files and every generation option, as plain JSON.

The same state is saved to a ``.mgtws`` workspace file (File > Save Workspace) and, on close,
to QSettings so the last session comes back on its own.
"""
import json
import os
from pathlib import Path

from ..core.geo_utils import DEFAULT_BBOX

WORKSPACE_VERSION = 1
WORKSPACE_FILTER = "Map Generator Workspace (*.mgtws);;JSON (*.json)"


PATH_FIELDS = ("outPath", "packageDir")  # plain strings in the state, next to the per-layer "files" map


def _to_portable(value, base):
    """Absolute path -> forward-slash path relative to the workspace file (kept as-is if that is impossible)."""
    if not value or not os.path.isabs(value):
        return value
    try:
        return Path(os.path.relpath(value, base)).as_posix()
    except ValueError:  # other drive on Windows: no relative form exists
        return value


def _from_portable(value, base):
    """Relative path in a workspace file -> path resolved against the workspace file's folder."""
    if not value or os.path.isabs(value) or base is None:
        return value
    return os.path.normpath(Path(base) / value)


def collect_state(window):
    return {
        "version": WORKSPACE_VERSION,
        "files": dict(window.files),
        "outPath": window.out_path.text(),
        "packageDir": window.package_dir.text(),
        "mapKey": window.map_key.text(),
        "mapName": window.map_name.text(),
        "mapVersion": window.map_version.text(),
        "projectionMode": window.projection.currentData(),
        "worldWidth": window.world_width.value(),
        "worldHeight": window.world_height.value(),
        "useBorders": window.use_borders.isChecked(),
        "lloyd": window.lloyd.isChecked(),
        "lloydIter": window.lloyd_iter.value(),
        "river": window.river.isChecked(),
        "riverStrength": window.river_strength.value(),
        "smoothing": window.smoothing.isChecked(),
        "smoothingMethod": window.smoothing_method.currentText(),
        "smoothingIter": window.smoothing_iter.value(),
        "smoothingStrength": window.smoothing_strength.value(),
        "seaCellScale": window.sea_cell_scale.value(),
        "seaSeed": window.sea_seed.value(),
        "emptyPolicyDefault": window.policy_default.currentData(),
        "emptyOverrides": dict(window.empty_overrides),
        "bbox": [spin.value() for spin in window.bbox_inputs],
        "overlays": {key: box.isChecked() for key, box in window.overlay_checks.items()},
    }


def apply_state(window, state, base_dir=None):
    """Apply a saved state to the window. Returns the list of input files that could not be loaded."""
    def setv(widget, value, setter="setValue"):
        if value is not None:
            getattr(widget, setter)(value)

    setv(window.out_path, _from_portable(state.get("outPath"), base_dir), "setText")
    setv(window.package_dir, _from_portable(state.get("packageDir"), base_dir), "setText")
    setv(window.map_key, state.get("mapKey"), "setText")
    setv(window.map_name, state.get("mapName"), "setText")
    setv(window.map_version, state.get("mapVersion"), "setText")
    window.projection.setCurrentIndex(max(0, window.projection.findData(state.get("projectionMode", "lcc"))))
    setv(window.world_width, state.get("worldWidth"))
    setv(window.world_height, state.get("worldHeight"))
    window.use_borders.setChecked(bool(state.get("useBorders", False)))
    window.lloyd.setChecked(bool(state.get("lloyd", False)))
    setv(window.lloyd_iter, state.get("lloydIter"))
    window.river.setChecked(bool(state.get("river", False)))
    setv(window.river_strength, state.get("riverStrength"))
    window.smoothing.setChecked(bool(state.get("smoothing", False)))
    setv(window.smoothing_iter, state.get("smoothingIter"))
    setv(window.smoothing_strength, state.get("smoothingStrength"))
    index = window.smoothing_method.findText(state.get("smoothingMethod", "chaikin"))
    if index >= 0:
        window.smoothing_method.setCurrentIndex(index)
    setv(window.sea_cell_scale, state.get("seaCellScale"))
    setv(window.sea_seed, state.get("seaSeed"))
    index = window.policy_default.findData(state.get("emptyPolicyDefault"))
    if index >= 0:
        window.policy_default.setCurrentIndex(index)
    window.empty_overrides = dict(state.get("emptyOverrides") or {})
    bbox = state.get("bbox")
    for i, value in enumerate(bbox if isinstance(bbox, list) and len(bbox) == 4 else DEFAULT_BBOX):
        window.bbox_inputs[i].setValue(float(value))
    for key, checked in (state.get("overlays") or {}).items():
        if key in window.overlay_checks:
            window.overlay_checks[key].setChecked(bool(checked))

    missing = []
    for key, row in window.file_rows.items():
        path = (state.get("files") or {}).get(key)
        if not path:
            row.set_path(None, notify=False)
            window.files.pop(key, None)
            window.layers.pop(key, None)
            continue
        resolved = Path(_from_portable(path, base_dir))
        if not resolved.exists():
            missing.append(str(resolved))
            continue
        row.set_path(str(resolved), notify=False)
        window.load_layer_file(key, str(resolved))
    return missing


def save_file(window, path):
    state = collect_state(window)
    base = Path(path).resolve().parent
    # Everything is stored relative to the workspace file (forward slashes) so the workspace folder
    # can be copied to another machine or OS and still open.
    state["files"] = {key: _to_portable(value, base) for key, value in state["files"].items()}
    for field in PATH_FIELDS:
        state[field] = _to_portable(state[field], base)
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_file(window, path):
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(state, dict) or "files" not in state:
        raise ValueError("This is not a Map Generator workspace file.")
    return apply_state(window, state, Path(path).resolve().parent)
