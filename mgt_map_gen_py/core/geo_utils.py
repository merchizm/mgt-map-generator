import base64
import hashlib
import json
import math
import time
import unicodedata
from pathlib import Path

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.ops import linemerge, nearest_points, unary_union
from shapely.validation import make_valid


DEFAULT_BBOX = [-25, 15, 65, 72]
EMPTY_COUNTRY_POLICIES = {
    "merge": "merge_to_nearest_smallest_land",
    "lake": "convert_to_lake",
    "empty": "keep_empty_land",
}
LAYER_ORDER = [
    "cities",
    "seaCities",
    "land",
    "lakes",
    "borders",
    "oceans",
    "rivers",
    "output",
    "generatedCities",
    "seaRegions",
    "movementNodes",
    "movementEdges",
    "railNodes",
    "railEdges",
    "oceanMask",
    "lakesMask",
    "syntheticLakes",
    "emptyLands",
    "mergedEmptyCountries",
]
LAYER_LABELS = {
    "cities": "Input Cities",
    "seaCities": "Sea Seeds",
    "land": "Land",
    "lakes": "Lakes",
    "borders": "Borders",
    "oceans": "Oceans",
    "rivers": "Rivers",
    "output": "Provinces",
    "generatedCities": "Pkg Cities",
    "seaRegions": "Sea Regions",
    "movementNodes": "Move Nodes",
    "movementEdges": "Move Edges",
    "railNodes": "Rail Nodes",
    "railEdges": "Rail Edges",
    "oceanMask": "Ocean Mask",
    "lakesMask": "Lake Mask",
    "syntheticLakes": "Synthetic Lakes",
    "emptyLands": "Empty Lands",
    "mergedEmptyCountries": "Merged Empty",
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def inspect_geometry_kinds(geojson):
    kinds = set()

    def push_geometry(geometry):
        if not geometry:
            return
        if geometry.get("type") == "GeometryCollection":
            for child in geometry.get("geometries") or []:
                push_geometry(child)
            return
        kinds.add(geometry.get("type"))

    if geojson.get("type") == "FeatureCollection":
        for item in geojson.get("features") or []:
            push_geometry(item.get("geometry"))
    elif geojson.get("type") == "Feature":
        push_geometry(geojson.get("geometry"))
    else:
        push_geometry(geojson)
    return sorted(kind for kind in kinds if kind)


def validate_geometry_kinds(geojson, label, allowed):
    kinds = inspect_geometry_kinds(geojson)
    if not kinds:
        raise ValueError(f"No geometry was found in the {label} file.")
    invalid = [kind for kind in kinds if kind not in allowed]
    if invalid:
        raise ValueError(
            f"{label} expects {'/'.join(allowed)}, but contains {', '.join(invalid)}."
        )


def normalize_value(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    out = []
    last_space = False
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
            last_space = False
        elif not last_space:
            out.append(" ")
            last_space = True
    return "".join(out).strip()


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    normalized = normalize_value(value)
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


class RegionKeyFactory:
    def __init__(self):
        self.counter = 0

    def __call__(self, properties=None):
        self.counter += 1
        properties = properties or {}
        raw_name = str(properties.get("name") or "").strip()
        normalized_name = normalize_value(raw_name) or "region"
        normalized_country = normalize_value(properties.get("country")) or "world"
        encoded = base64.urlsafe_b64encode((raw_name or normalized_name).encode("utf-8")).decode("ascii").rstrip("=")
        timestamp = int(time.time() * 1000)
        raw = f"{raw_name}|{normalized_name}|{normalized_country}|{timestamp}|{self.counter}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        return f"{base36(timestamp).rjust(9, '0')}-{base36(self.counter).rjust(3, '0')}-{digest}-{encoded}"


def base36(value):
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    value = int(value)
    if value == 0:
        return "0"
    parts = []
    while value:
        value, rem = divmod(value, 36)
        parts.append(alphabet[rem])
    return "".join(reversed(parts))


def build_region_properties(source, key_factory, include_main_city=False, default_main_city=None, force_country_null=False):
    props = dict(source or {})
    has_main = "main_city" in props or "mainCity" in props
    props.pop("mainCity", None)
    if include_main_city and has_main:
        normalized = normalize_bool(props.get("main_city"))
        props["main_city"] = bool(default_main_city) if normalized is None and default_main_city is not None else bool(normalized)
    elif default_main_city is not None:
        props["main_city"] = bool(default_main_city)
    else:
        props.pop("main_city", None)
    if force_country_null:
        props["country"] = None
    else:
        country = props.get("country")
        props["country"] = None if country is None or str(country).strip() == "" else country
    props["key"] = key_factory(props)
    return props


def sanitize_properties(properties, overrides=None):
    props = dict(properties or {})
    props.pop("__sourceId", None)
    props.update(overrides or {})
    if props.get("country") in (None, "", "SEA") or "country" not in props:
        props["country"] = None
    if "main_city" in props:
        props["main_city"] = bool(props["main_city"])
    return props


def feature(geom, props=None):
    return {"type": "Feature", "properties": dict(props or {}), "geometry": mapping(geom)}


def feature_collection(features=None):
    return {"type": "FeatureCollection", "features": list(features or [])}


def iter_features(geojson):
    if not geojson:
        return
    if geojson.get("type") == "FeatureCollection":
        yield from geojson.get("features") or []
    elif geojson.get("type") == "Feature":
        yield geojson
    else:
        yield {"type": "Feature", "properties": {}, "geometry": geojson}


def geometry_from_feature(item):
    try:
        return shape(item.get("geometry") if item.get("type") == "Feature" else item)
    except Exception:
        return GeometryCollection()


def clean_geom(geom, min_area_deg=0.000002):
    if geom.is_empty:
        return GeometryCollection()
    try:
        geom = make_valid(geom)
    except Exception:
        geom = geom.buffer(0)
    if geom.is_empty:
        return GeometryCollection()
    if isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty]
        geom = unary_union(polys) if polys else GeometryCollection()
    if isinstance(geom, (Polygon, MultiPolygon)):
        min_area = min_area_deg
        parts = []
        geoms = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
        for part in geoms:
            if part.area >= min_area:
                parts.append(part)
        return unary_union(parts) if parts else GeometryCollection()
    return geom


def polygon_geometries(geojson, label):
    out = []
    for item in iter_features(geojson):
        props = item.get("properties") or {}
        geom = geometry_from_feature(item)
        if isinstance(geom, (Polygon, MultiPolygon)):
            out.append((geom, props))
        elif isinstance(geom, GeometryCollection):
            for child in geom.geoms:
                if isinstance(child, (Polygon, MultiPolygon)):
                    out.append((child, props))
    if not out:
        raise ValueError(f"{label} must contain Polygon or MultiPolygon geometries.")
    return out


def line_geometries(geojson):
    out = []
    for item in iter_features(geojson):
        props = item.get("properties") or {}
        geom = geometry_from_feature(item)
        if isinstance(geom, (LineString, MultiLineString)):
            out.append((geom, props))
        elif isinstance(geom, (Polygon, MultiPolygon)):
            out.append((geom.boundary, props))
        elif isinstance(geom, GeometryCollection):
            for child in geom.geoms:
                if isinstance(child, (LineString, MultiLineString)):
                    out.append((child, props))
    return out


def point_features(geojson, label, prefix):
    features = []
    for index, item in enumerate(iter_features(geojson), start=1):
        geom = geometry_from_feature(item)
        if isinstance(geom, Point):
            props = dict(item.get("properties") or {})
            props["__sourceId"] = f"{prefix}-{index}"
            features.append({"geom": geom, "properties": props})
    if label == "cities" and not features:
        raise ValueError("No Point features found in cities geojson.")
    return features


def merge_polygons(geojson, label):
    return clean_geom(unary_union([geom for geom, _ in polygon_geometries(geojson, label)]))


def bbox_polygon(bbox):
    return box(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))


def preclip(geom, bbox):
    clipped = clean_geom(geom.intersection(bbox_polygon(bbox)))
    return clipped if not clipped.is_empty else geom


def expand_bounds(bounds, pad=0.35):
    return [bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad]


def get_border_aliases(props):
    candidates = [
        "ISO_A2", "ISO_A2_EH", "ISO_A3", "ISO_A3_EH", "ADM0_A3", "SOV_A3", "GU_A3",
        "SU_A3", "BRK_A3", "WB_A2", "WB_A3", "POSTAL", "ADMIN", "NAME", "NAME_LONG",
        "NAME_EN", "NAME_SORT", "SOVEREIGNT", "FORMAL_EN", "GEOUNIT", "SUBUNIT",
        "country", "COUNTRY",
    ]
    return list(dict.fromkeys(normalize_value(props.get(key)) for key in candidates if normalize_value(props.get(key))))


def get_city_country_keys(props):
    candidates = ["country", "COUNTRY", "country_code", "COUNTRY_CODE", "iso_a2", "iso_a3", "ISO_A2", "ISO_A3", "ADMIN", "NAME"]
    return list(dict.fromkeys(normalize_value(props.get(key)) for key in candidates if normalize_value(props.get(key))))


def country_display_name(props):
    return props.get("ADMIN") or props.get("NAME_LONG") or props.get("NAME") or props.get("SOVEREIGNT") or props.get("FORMAL_EN") or props.get("ISO_A3") or "Unknown"


def geojson_from_points(points):
    return feature_collection([feature(item["geom"], sanitize_properties(item["properties"])) for item in points])


def to_public_feature(geom, props, overrides=None):
    return feature(geom, sanitize_properties(props, overrides))


def distance_km(a, b):
    return a.distance(b) * 111.32


def line_length_km(geom):
    return geom.length * 111.32


def representative_point(geom, preferred=None):
    if preferred is not None and geom.contains(preferred):
        return preferred
    try:
        return geom.representative_point()
    except Exception:
        return geom.centroid


def sanitize_map_key(value):
    return normalize_value(value).replace(" ", "-") or "generated-map"


def display_map_name(key):
    return " ".join(part.capitalize() for part in str(key or "Generated Map").split("-") if part)
