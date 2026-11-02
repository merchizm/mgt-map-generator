"""Map projections used while generating a package.

The generator works in "work units" (projected km / ``WORK_KM``, so one unit is roughly one
degree of latitude) which keeps all degree-tuned tolerances meaningful. Package files are
written in projected kilometres (``to_km``); the desktop preview gets lon/lat (``to_lonlat``).
"""
import math

import numpy as np
import shapely
from shapely.geometry import box
from shapely.ops import transform as _transform  # noqa: F401  (kept for parity with shapely API)

from .geo_utils import EARTH_RADIUS_KM

WORK_KM = 111.195  # km per work unit (~ one degree of latitude)
EUROPE_BBOX = [-25, 15, 65, 72]
SEGMENT_DEG = 0.25  # densify long lon/lat edges before projecting so they curve correctly


def _as_array_fn(fn):
    return lambda coords: np.column_stack(fn(coords[:, 0], coords[:, 1]))


class LonLatProjection:
    """Identity: keep plain lon/lat (legacy behaviour)."""

    name = "lonlat"
    projected = False

    def params(self):
        return {"type": "lonlat", "units": "degrees"}

    def forward_xy(self, lon, lat):
        return np.asarray(lon, float), np.asarray(lat, float)

    def inverse_xy(self, x, y):
        return np.asarray(x, float), np.asarray(y, float)

    def to_work(self, geom):
        return geom

    def to_lonlat(self, geom):
        return geom

    def to_km(self, geom):
        return geom

    def work_bounds(self, bbox_ll):
        return [float(v) for v in bbox_ll]

    def km_per_work_unit(self):
        return 1.0


class LambertConformalConic(LonLatProjection):
    """Spherical Lambert conformal conic, output in km with the origin at (lon0, lat0), y pointing north."""

    projected = True

    def __init__(self, lon0, lat0, lat1, lat2, name="lcc-custom", radius_km=EARTH_RADIUS_KM):
        for lat in (lat0, lat1, lat2):
            if not -85 < lat < 85:
                raise ValueError("Lambert conformal conic needs latitudes inside (-85, 85).")
        self.name = name
        self.lon0, self.lat0, self.lat1, self.lat2, self.radius = lon0, lat0, lat1, lat2, radius_km
        p0, p1, p2 = map(math.radians, (lat0, lat1, lat2))
        tan = lambda p: math.tan(math.pi / 4 + p / 2)
        if abs(p1 - p2) < 1e-9:
            self.n = math.sin(p1)
        else:
            self.n = math.log(math.cos(p1) / math.cos(p2)) / math.log(tan(p2) / tan(p1))
        self.f = math.cos(p1) * tan(p1) ** self.n / self.n
        self.rho0 = radius_km * self.f / tan(p0) ** self.n

    @classmethod
    def for_bbox(cls, bbox, name=None):
        min_lng, min_lat, max_lng, max_lat = bbox
        span = max_lat - min_lat
        lat1, lat2 = min_lat + span / 6, max_lat - span / 6
        return cls((min_lng + max_lng) / 2, (min_lat + max_lat) / 2, lat1, lat2, name or "lcc-custom")

    def params(self):
        return {
            "type": "lambert_conformal_conic",
            "units": "km",
            "sphereRadiusKm": self.radius,
            "lon0": self.lon0,
            "lat0": self.lat0,
            "lat1": self.lat1,
            "lat2": self.lat2,
            "xAxis": "east",
            "yAxis": "north",
        }

    def forward_xy(self, lon, lat):
        lon, lat = np.asarray(lon, float), np.asarray(lat, float)
        rho = self.radius * self.f / np.tan(np.pi / 4 + np.radians(lat) / 2) ** self.n
        theta = self.n * np.radians(lon - self.lon0)
        return rho * np.sin(theta), self.rho0 - rho * np.cos(theta)

    def inverse_xy(self, x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        dy = self.rho0 - y
        rho = np.sign(self.n) * np.hypot(x, dy)
        theta = np.arctan2(np.sign(self.n) * x, np.sign(self.n) * dy)
        lat = 2 * np.arctan((self.radius * self.f / rho) ** (1 / self.n)) - np.pi / 2
        return self.lon0 + np.degrees(theta / self.n), np.degrees(lat)

    def to_work(self, geom):
        if geom.is_empty:
            return geom
        geom = shapely.segmentize(geom, SEGMENT_DEG)
        fn = _as_array_fn(lambda x, y: tuple(v / WORK_KM for v in self.forward_xy(x, y)))
        return shapely.transform(geom, fn)

    def to_lonlat(self, geom):
        if geom.is_empty:
            return geom
        return shapely.transform(geom, _as_array_fn(lambda x, y: self.inverse_xy(x * WORK_KM, y * WORK_KM)))

    def to_km(self, geom):
        if geom.is_empty:
            return geom
        return shapely.transform(geom, lambda coords: coords * WORK_KM)

    def work_bounds(self, bbox_ll):
        ring = shapely.segmentize(box(*bbox_ll), SEGMENT_DEG)
        return [float(v) for v in self.to_work(ring).bounds]

    def km_per_work_unit(self):
        return WORK_KM


def build_projection(mode, bbox_ll):
    if mode in (None, "", "lcc"):
        if [float(v) for v in bbox_ll] == [float(v) for v in EUROPE_BBOX]:
            # Standard parallels hugging where the cities are (35-65N) keep scale ~1 for the whole game map.
            return LambertConformalConic(20.0, 52.0, 35.0, 65.0, "lcc-europe")
        return LambertConformalConic.for_bbox(bbox_ll, "lcc-custom")
    if mode == "lonlat":
        return LonLatProjection()
    raise ValueError(f"Unknown projection mode: {mode!r} (expected 'lcc' or 'lonlat').")
