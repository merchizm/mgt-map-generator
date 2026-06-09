from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points, unary_union

from .geo_utils import clean_geom


def chaikin_ring(coords, iterations):
    current = list(coords)
    if current[0] == current[-1]:
        current = current[:-1]
    for _ in range(max(1, int(iterations))):
        next_coords = []
        for index, a in enumerate(current):
            b = current[(index + 1) % len(current)]
            next_coords.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            next_coords.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        current = next_coords
    return current + [current[0]]


def bezier_ring(coords, iterations, strength):
    current = list(coords)
    if current[0] == current[-1]:
        current = current[:-1]
    t = max(0.12, min(0.4, float(strength)))
    for _ in range(max(1, int(iterations))):
        next_coords = []
        for index, curr in enumerate(current):
            prev = current[(index - 1) % len(current)]
            nxt = current[(index + 1) % len(current)]
            after = current[(index + 2) % len(current)]
            out = (
                curr[0] + (nxt[0] - prev[0]) * t * 0.35,
                curr[1] + (nxt[1] - prev[1]) * t * 0.35,
            )
            incoming = (
                nxt[0] - (after[0] - curr[0]) * t * 0.35,
                nxt[1] - (after[1] - curr[1]) * t * 0.35,
            )
            next_coords.extend([curr, out, incoming])
        current = next_coords
    return current + [current[0]]


def smooth_geom(geom, method="chaikin", iterations=1, strength=0.24):
    if geom.is_empty:
        return geom
    geoms = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    out = []
    for poly in geoms:
        exterior = (
            bezier_ring(poly.exterior.coords, iterations, strength)
            if method == "bezier"
            else chaikin_ring(poly.exterior.coords, iterations)
        )
        out.append(Polygon(exterior, [ring.coords for ring in poly.interiors]))
    return clean_geom(unary_union(out))


def nudge_coordinate_toward_lines(coord, river_items, strength, radius_deg=0.45):
    point = Point(coord)
    current = point
    for river, _ in river_items:
        if river.is_empty or river.distance(current) > radius_deg:
            continue
        _, nearest = nearest_points(current, river)
        distance = current.distance(nearest)
        if distance > radius_deg:
            continue
        weight = (1 - distance / radius_deg) * max(0, min(1, float(strength)))
        current = Point(
            current.x + (nearest.x - current.x) * weight,
            current.y + (nearest.y - current.y) * weight,
        )
    return current.x, current.y


def influence_ring(coords, river_items, strength):
    values = list(coords)
    if len(values) < 4:
        return values
    closed = values[0] == values[-1]
    body = values[:-1] if closed else values
    influenced = []
    for index, coord in enumerate(body):
        influenced.append(
            coord if index == 0 or index == len(body) - 1 else nudge_coordinate_toward_lines(coord, river_items, strength)
        )
    if closed:
        influenced.append(influenced[0])
    return influenced


def apply_river_influence(geom, river_items, strength):
    if geom.is_empty or not river_items or strength <= 0:
        return geom
    geoms = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    adjusted = []
    for poly in geoms:
        exterior = influence_ring(poly.exterior.coords, river_items, strength)
        adjusted.append(Polygon(exterior, [ring.coords for ring in poly.interiors]))
    candidate = clean_geom(unary_union(adjusted))
    if candidate.is_empty or candidate.area < geom.area * 0.94:
        return geom
    clipped = clean_geom(candidate.intersection(geom.buffer(0.02)))
    return clipped if not clipped.is_empty and clipped.area >= geom.area * 0.9 else geom


def clip_region(cell, country_mask, land_mask, lakes_mask, options, warnings, context):
    current = cell
    if country_mask is not None:
        current = clean_geom(current.intersection(country_mask))
        if current.is_empty:
            warnings.push("country_clip_empty", "Province disappeared after country clipping.", context)
            return None
    current = clean_geom(current.intersection(land_mask))
    if current.is_empty:
        warnings.push("land_clip_empty", "Province disappeared after land clipping.", context)
        return None
    if options.get("riverInfluenceEnabled"):
        candidate = apply_river_influence(
            current,
            options.get("riverFeatures", []),
            float(options.get("riverInfluenceStrength", 0.32)),
        )
        if candidate.equals(current):
            warnings.push("river_influence_noop", "River influence did not alter this province safely.", context)
        current = candidate
    if lakes_mask is not None and not lakes_mask.is_empty:
        diff = clean_geom(current.difference(lakes_mask))
        if not diff.is_empty:
            current = diff
        else:
            warnings.push("lake_difference_failed", "Lake subtraction failed; province was kept as-is.", context)
    if options.get("smoothingEnabled"):
        candidate = smooth_geom(
            current,
            options.get("smoothingMethod", "chaikin"),
            options.get("smoothingIterations", 1),
            options.get("smoothingStrength", 0.24),
        )
        if not candidate.is_empty and candidate.area >= current.area * 0.96:
            current = candidate.intersection(current)
        else:
            warnings.push("smoothing_fallback", "Smoothed geometry failed area-retention checks. Original geometry was kept.", context)
    current = clean_geom(current)
    return None if current.is_empty else current
