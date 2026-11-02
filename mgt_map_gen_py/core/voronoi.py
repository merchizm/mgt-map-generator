import math

import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import GeometryCollection, LineString, Polygon, box
from shapely.ops import split

from .geo_utils import clean_geom


def finite_voronoi_polygons(points, bbox):
    coords = np.array([[p.x, p.y] for p in points], dtype=float)
    bounds_poly = box(*bbox)
    if len(coords) == 1:
        return [bounds_poly]
    if len(coords) == 2:
        a, b = coords
        mid = (a + b) / 2.0
        dx, dy = b - a
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        far = max(abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1])) * 4
        divider = LineString([
            (mid[0] - nx * far, mid[1] - ny * far),
            (mid[0] + nx * far, mid[1] + ny * far),
        ])
        parts = list(split(bounds_poly, divider).geoms)
        return [min(parts, key=lambda part: part.distance(point)) for point in points]

    # Separate coincident seeds by a negligible, deterministic offset so qhull
    # does not drop them (the shifted duplicate ends up with a sliver cell).
    coords = _jitter_duplicates(coords, bbox)
    try:
        vor = Voronoi(coords)
        regions, vertices = _finite_polygons_2d(vor)
    except Exception:  # collinear seeds etc. (QhullError, missing ridges)
        return _halfplane_cells(coords, bounds_poly)
    cells = [
        clean_geom(Polygon(vertices[region]).intersection(bounds_poly)) if len(region) >= 3 else GeometryCollection()
        for region in regions
    ]
    # The cells of a Voronoi diagram tile the bounds exactly. Nearly-collinear seeds can make the
    # far-point reconstruction produce garbage, so verify the tiling and fall back to the exact method.
    if abs(sum(cell.area for cell in cells) - bounds_poly.area) > 1e-3 * bounds_poly.area:
        return _halfplane_cells(coords, bounds_poly)
    return cells


def _jitter_duplicates(coords, bbox):
    eps = max(abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1]), 1.0) * 1e-9
    seen = {}
    out = coords.copy()
    for index, (x, y) in enumerate(map(tuple, coords)):
        count = seen.get((x, y), 0)
        seen[(x, y)] = count + 1
        if count:
            out[index] = (x + eps * count, y + eps * count * 0.5)
    return out


def _halfplane_cells(coords, bounds_poly):
    """O(n^2) exact Voronoi fallback for degenerate inputs: clip bounds by each bisector."""
    far = max(bounds_poly.bounds[2] - bounds_poly.bounds[0], bounds_poly.bounds[3] - bounds_poly.bounds[1]) * 4 or 1.0
    cells = []
    for i, a in enumerate(coords):
        cell = bounds_poly
        for j, b in enumerate(coords):
            if i == j or cell.is_empty:
                continue
            mid = (a + b) / 2.0
            d = b - a
            norm = math.hypot(*d) or 1.0
            n = d / norm
            t = np.array([-n[1], n[0]])
            half = Polygon([
                mid + t * far,
                mid - t * far,
                mid - t * far - n * far,
                mid + t * far - n * far,
            ])
            cell = cell.intersection(half)
        cells.append(clean_geom(cell))
    return cells


def _finite_polygons_2d(vor, radius=None):
    if vor.points.shape[1] != 2:
        raise ValueError("Requires 2D input")
    new_regions = []
    new_vertices = vor.vertices.tolist()
    center = vor.points.mean(axis=0)
    if radius is None:
        radius = np.ptp(vor.points, axis=0).max() * 4

    all_ridges = {}
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        all_ridges.setdefault(p1, []).append((p2, v1, v2))
        all_ridges.setdefault(p2, []).append((p1, v1, v2))

    for p1, region_index in enumerate(vor.point_region):
        vertices = vor.regions[region_index]
        if all(v >= 0 for v in vertices):
            new_regions.append(vertices)
            continue
        ridges = all_ridges[p1]
        new_region = [v for v in vertices if v >= 0]
        for p2, v1, v2 in ridges:
            if v2 < 0:
                v1, v2 = v2, v1
            if v1 >= 0:
                continue
            tangent = vor.points[p2] - vor.points[p1]
            tangent /= np.linalg.norm(tangent)
            normal = np.array([-tangent[1], tangent[0]])
            midpoint = vor.points[[p1, p2]].mean(axis=0)
            direction = np.sign(np.dot(midpoint - center, normal)) * normal
            far_point = vor.vertices[v2] + direction * radius
            new_region.append(len(new_vertices))
            new_vertices.append(far_point.tolist())
        vertices_array = np.asarray([new_vertices[v] for v in new_region])
        centroid = vertices_array.mean(axis=0)
        angles = np.arctan2(vertices_array[:, 1] - centroid[1], vertices_array[:, 0] - centroid[0])
        new_regions.append(np.array(new_region)[np.argsort(angles)].tolist())
    return new_regions, np.asarray(new_vertices)
