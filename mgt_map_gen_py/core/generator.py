from __future__ import annotations

import datetime as _dt
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from .geometry_ops import clip_region
from .geo_utils import (
    DEFAULT_BBOX,
    EMPTY_COUNTRY_POLICIES,
    RegionKeyFactory,
    build_region_properties,
    clean_geom,
    country_display_name,
    display_map_name,
    distance_km,
    expand_bounds,
    feature,
    feature_collection,
    get_border_aliases,
    get_city_country_keys,
    line_geometries,
    line_length_km,
    merge_polygons,
    normalize_value,
    point_features,
    polygon_geometries,
    preclip,
    read_json,
    representative_point,
    sanitize_map_key,
    to_public_feature,
    transform_collection,
    validate_geometry_kinds,
    write_json,
)
from .projection import WORK_KM, build_projection
from .voronoi import finite_voronoi_polygons


DEFAULT_SEA_CELL_SCALE = 3.0
MAX_AUTO_SEA_SEEDS = 500

DEFAULT_INPUTS = {
    "cities": "cities.geojson",
    "seaCities": "sea-cities.geojson",
    "land": "lands.json",
    "lakes": "lakes.json",
    "borders": "borders.geojson",
    "oceans": "oceans.json",
    "rivers": "rivers.geojson",
    "out": "provinces.geojson",
    "bbox": DEFAULT_BBOX,
}


@dataclass
class WarningCollector:
    warnings: list[dict] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)

    def push(self, code, message, context=None):
        context = context or {}
        key = json.dumps([code, message, context.get("country", ""), context.get("city", ""), context.get("seaBodyId", "")], sort_keys=True)
        if key in self._seen:
            return
        self._seen.add(key)
        self.warnings.append({"code": code, "message": message, "context": context})


def report(callback, percent, stage, detail=""):
    if callback:
        callback({"percent": int(max(0, min(100, round(percent)))), "stage": stage, "detail": detail})


def build_country_catalog(borders_geojson, bbox, proj=None):
    groups = {}
    for geom, props in polygon_geometries(borders_geojson, "borders"):
        name = country_display_name(props)
        key = normalize_value(name)
        entry = groups.setdefault(key, {"key": key, "name": name, "aliases": set(), "geoms": []})
        entry["geoms"].append(geom)
        entry["aliases"].update(get_border_aliases(props))
    countries = []
    clip = box(*bbox)
    for entry in groups.values():
        mask = clean_geom(unary_union(entry["geoms"]).intersection(clip))
        if mask.is_empty:
            continue
        if proj is not None:
            mask = clean_geom(proj.to_work(mask))
        country = {
            "key": entry["key"],
            "name": entry["name"],
            "aliases": sorted(entry["aliases"]),
            "mask": mask,
            "centroid": mask.centroid,
            "area": mask.area,
            "bbox": list(mask.bounds),
        }
        countries.append(country)
    # A country's own key always wins; aliases (e.g. SOVEREIGNT shared by
    # Greenland and Denmark) only fill gaps so they cannot steal another country's key.
    alias_map = {}
    for country in countries:
        alias_map[country["key"]] = country
    for country in countries:
        for alias in country["aliases"]:
            alias_map.setdefault(alias, country)
    return countries, alias_map


def find_country_for_city(props, alias_map):
    for key in get_city_country_keys(props):
        if key in alias_map:
            return alias_map[key]
    return None


def relax_points(points, allowed_mask, bbox, iterations):
    current = list(points)
    for _ in range(max(1, int(iterations))):
        cells = finite_voronoi_polygons([p["geom"] for p in current], bbox)
        next_points = []
        for item, cell in zip(current, cells):
            clipped = clean_geom(cell.intersection(allowed_mask)) if allowed_mask is not None else cell
            if clipped.is_empty:
                next_points.append(item)
                continue
            moved = dict(item)
            moved["geom"] = clipped.representative_point()
            next_points.append(moved)
        current = next_points
    return current


def split_components(mask, prefix="component"):
    if mask is None or mask.is_empty:
        return []
    geoms = mask.geoms if mask.geom_type == "MultiPolygon" else [mask]
    components = []
    for index, geom in enumerate(geoms, start=1):
        clean = clean_geom(geom)
        if clean.is_empty:
            continue
        components.append({
            "id": f"{prefix}-{index}",
            "index": index,
            "mask": clean,
            "bbox": list(clean.bounds),
            "area": clean.area,
            "centroid": clean.centroid,
        })
    return components


def auto_sea_seeds(component, target_area, seed):
    """Deterministic pseudo-random seed points inside a sea body, evened out with Lloyd relaxation."""
    mask = component["mask"]
    count = int(max(1, min(MAX_AUTO_SEA_SEEDS, round(component["area"] / target_area))))
    if count == 1:
        return [{"geom": mask.representative_point(), "properties": {}}]
    rng = np.random.default_rng(seed + component["index"])
    min_x, min_y, max_x, max_y = mask.bounds
    xs, ys = [], []
    for _ in range(40):
        cand_x = rng.uniform(min_x, max_x, count * 4)
        cand_y = rng.uniform(min_y, max_y, count * 4)
        inside = shapely.contains_xy(mask, cand_x, cand_y)
        xs.extend(cand_x[inside])
        ys.extend(cand_y[inside])
        if len(xs) >= count:
            break
    if not xs:
        return [{"geom": mask.representative_point(), "properties": {}}]
    points = [{"geom": Point(x, y), "properties": {}} for x, y in zip(xs[:count], ys[:count])]
    if len(points) > 1:
        points = relax_points(points, mask, expand_bounds(component["bbox"], 0.35), 2)
    return points


def generate_open_water(points, ocean_mask, ocean_components, options, warnings, key_factory, progress, target_area=None):
    regions = []
    if ocean_mask is None or ocean_mask.is_empty:
        return regions
    report(progress, 90, "building-sea-regions", f"Processing {len(ocean_components)} separate sea bodies")
    cell_scale = max(0.1, float(options.get("seaAutoCellScale") or DEFAULT_SEA_CELL_SCALE))
    sea_seed = int(options.get("seaSeed") if options.get("seaSeed") is not None else 1)
    for component in ocean_components:
        seeds = [p for p in points if component["mask"].contains(p["geom"])]
        if options.get("lloydEnabled") and len(seeds) > 1:
            seeds = relax_points(seeds, component["mask"], expand_bounds(component["bbox"], 0.35), options.get("lloydIterations", 1))
        if not seeds:
            seeds = auto_sea_seeds(component, (target_area or component["area"]) * cell_scale, sea_seed)
            for number, seed in enumerate(seeds, start=1):
                seed["properties"] = {"name": f"Sea {component['index']}-{number}", "synthetic": True}
        if len(seeds) == 1:
            seed = seeds[0]
            props = build_region_properties({**seed["properties"], "seaBodyId": component["id"], "seaBodyIndex": component["index"], "regionType": "sea"}, key_factory, default_main_city=False, force_country_null=True)
            regions.append({"geom": component["mask"], "properties": props})
            continue
        cells = finite_voronoi_polygons([p["geom"] for p in seeds], expand_bounds(component["bbox"], 0.35))
        for seed, cell in zip(seeds, cells):
            geom = clip_region(cell, None, component["mask"], None, {**options, "riverInfluenceEnabled": False}, warnings, {"city": seed["properties"].get("name", ""), "regionType": "sea", "seaBodyId": component["id"]})
            if geom is None:
                continue
            props = build_region_properties({**seed["properties"], "seaBodyId": component["id"], "seaBodyIndex": component["index"], "regionType": "sea"}, key_factory, default_main_city=False, force_country_null=True)
            regions.append({"geom": geom, "properties": props})
    return regions


def public_collection(regions, region_type=None):
    features = []
    for item in regions:
        overrides = {"regionType": region_type} if region_type else {}
        features.append(to_public_feature(item["geom"], item["properties"], overrides))
    return feature_collection(features)


def build_package(out_path, bbox, land_regions, sea_regions, city_points, sea_points, river_items, options, proj):
    out_path = Path(out_path)
    package_dir = Path(options.get("packageDir") or out_path.parent)
    paths = {
        "dir": str(package_dir.resolve()),
        "metadataPath": str((package_dir / "metadata.json").resolve()),
        "provincesPath": str((package_dir / "provinces.geojson").resolve()),
        "citiesPath": str((package_dir / "cities.geojson").resolve()),
        "seaRegionsPath": str((package_dir / "sea_regions.geojson").resolve()),
        "movementNodesPath": str((package_dir / "movement_nodes.geojson").resolve()),
        "movementEdgesPath": str((package_dir / "movement_edges.geojson").resolve()),
        "railNodesPath": str((package_dir / "rail_nodes.geojson").resolve()),
        "railEdgesPath": str((package_dir / "rail_edges.geojson").resolve()),
    }
    map_key = sanitize_map_key(options.get("mapKey") or package_dir.name or out_path.stem)
    metadata = {
        "key": map_key,
        "name": options.get("mapName") or display_map_name(map_key),
        "version": str(options.get("mapVersion") or _dt.date.today().isoformat()),
        "projection": proj.name,
        "projectionParams": proj.params(),
        "worldWidth": float(options.get("worldWidth") or abs(bbox[2] - bbox[0]) * proj.km_per_work_unit()),
        "worldHeight": float(options.get("worldHeight") or abs(bbox[3] - bbox[1]) * proj.km_per_work_unit()),
        "bounds": [round(v * proj.km_per_work_unit(), 3) for v in bbox],
    }

    all_regions = land_regions + sea_regions
    descriptors = []
    by_source = {p["properties"].get("__sourceId"): p for p in city_points + sea_points}
    for item in all_regions:
        props = item["properties"]
        node_type = "sea" if props.get("regionType") == "sea" else "land"
        source = by_source.get(props.get("__sourceId"))
        rep = representative_point(item["geom"], source["geom"] if source else None)
        descriptors.append({
            "item": item,
            "key": props.get("key"),
            "country": props.get("country"),
            "nodeType": node_type,
            "rep": rep,
            "bounds": item["geom"].bounds,
            "mainCity": bool(props.get("main_city")) if node_type == "land" else False,
            "nodeKey": f"{node_type}:{props.get('key')}",
            "port": False,
        })

    for desc in descriptors:
        desc["node"] = Point(desc["rep"].x, desc["rep"].y)
        desc["lonlat"] = proj.to_lonlat(desc["node"])

    def bounds_overlap(a, b):
        return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

    river_geoms = [geom for geom, _ in river_items]
    movement_edges = []
    seen_edges = set()
    for i, a in enumerate(descriptors):
        for b in descriptors[i + 1:]:
            if not bounds_overlap(a["bounds"], b["bounds"]):
                continue
            shared = a["item"]["geom"].boundary.intersection(b["item"]["geom"].boundary)
            shared_km = shared.length * WORK_KM if proj.projected else line_length_km(shared)
            if shared.is_empty or shared_km <= 0.001:
                continue
            edge_type = "port" if {a["nodeType"], b["nodeType"]} == {"land", "sea"} else a["nodeType"]
            key_parts = sorted([a["nodeKey"], b["nodeKey"]]) if edge_type != "port" else [a["nodeKey"], b["nodeKey"]]
            edge_key = "__".join(key_parts)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            line = LineString([a["node"], b["node"]])
            movement_edges.append(feature(line, {
                "key": edge_key,
                "from": key_parts[0],
                "to": key_parts[1],
                "edgeType": edge_type,
                "distance": round(distance_km(a["lonlat"], b["lonlat"]), 3),
                "riverCrossing": any(line.intersects(river) for river in river_geoms),
                "strait": False,
                "borderCrossing": a["country"] is not None and b["country"] is not None and a["country"] != b["country"],
            }))
            if edge_type == "port":
                a["port"] = a["nodeType"] == "land"
                b["port"] = b["nodeType"] == "land"

    # Built after the edge pass so the port flag (set while linking land to sea) is known.
    movement_nodes = [
        feature(desc["node"], {
            "key": desc["nodeKey"],
            "nodeType": desc["nodeType"],
            "sourceKey": desc["key"],
            "country": desc["country"] if desc["nodeType"] == "land" else None,
            "mainCity": desc["mainCity"],
            "port": desc["port"],
        })
        for desc in descriptors
    ]

    city_key_factory = RegionKeyFactory()
    cities = []
    rail_nodes = []
    for desc in descriptors:
        if desc["nodeType"] != "land":
            continue
        props = desc["item"]["properties"]
        cities.append(feature(desc["node"], {
            "key": city_key_factory({"name": props.get("name"), "country": desc["country"]}),
            "name": props.get("name") or "Unnamed City",
            "provinceKey": desc["key"],
            "country": desc["country"],
            "main_city": desc["mainCity"],
            "port": desc["port"],
        }))
        if desc["mainCity"]:
            rail_nodes.append(feature(desc["node"], {
                "key": f"rail:{desc['nodeKey']}",
                "linkedMovementNode": desc["nodeKey"],
                "nodeRole": "main_city",
                "country": desc["country"],
                "throughput": 1,
            }))

    package = {
        "metadata": metadata,
        "provinces": feature_collection([to_public_feature(item["geom"], item["properties"], {"regionType": item["properties"].get("regionType", "land")}) for item in all_regions]),
        "cities": feature_collection(cities),
        "seaRegions": public_collection(sea_regions, "sea"),
        "movementNodes": feature_collection(movement_nodes),
        "movementEdges": feature_collection(movement_edges),
        "railNodes": feature_collection(rail_nodes),
        "railEdges": feature_collection([]),
        "packagePaths": paths,
    }
    # Files are written in projected km (a no-op for lon/lat mode); `package` itself stays in work units.
    def exported(collection):
        return transform_collection(collection, proj.to_km) if proj.projected else collection

    exported_provinces = exported(package["provinces"])
    write_json(paths["metadataPath"], metadata)
    write_json(paths["provincesPath"], exported_provinces)
    write_json(paths["citiesPath"], exported(package["cities"]))
    write_json(paths["seaRegionsPath"], exported(package["seaRegions"]))
    write_json(paths["movementNodesPath"], exported(package["movementNodes"]))
    write_json(paths["movementEdgesPath"], exported(package["movementEdges"]))
    write_json(paths["railNodesPath"], exported(package["railNodes"]))
    write_json(paths["railEdgesPath"], package["railEdges"])
    if out_path.resolve() != Path(paths["provincesPath"]).resolve():
        write_json(out_path, exported_provinces)
    return package


def generate_provinces(options):
    progress = options.get("onProgress")
    warnings = WarningCollector()
    key_factory = RegionKeyFactory()
    bbox = [float(x) for x in (options.get("bbox") or DEFAULT_BBOX)]
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("Invalid bbox: expected [min_lng, min_lat, max_lng, max_lat] with min < max.")
    bbox_ll = bbox
    proj = build_projection(options.get("projectionMode"), bbox_ll)
    bbox = proj.work_bounds(bbox_ll)  # Voronoi/working bounds, in work units
    report(progress, 2, "reading-inputs", "Loading GeoJSON files")
    cities_geo = read_json(options["citiesPath"])
    sea_geo = read_json(options["seaCitiesPath"]) if options.get("seaCitiesPath") else None
    land_geo = read_json(options["landPath"])
    lakes_geo = read_json(options["lakesPath"]) if options.get("lakesPath") else None
    borders_geo = read_json(options["bordersPath"]) if options.get("useBorders") and options.get("bordersPath") else None
    oceans_geo = read_json(options["oceansPath"]) if options.get("oceansPath") else None
    rivers_geo = read_json(options["riversPath"]) if options.get("riversPath") else None
    validate_geometry_kinds(cities_geo, "Cities", ["Point"])
    validate_geometry_kinds(land_geo, "Land", ["Polygon", "MultiPolygon"])
    if sea_geo:
        validate_geometry_kinds(sea_geo, "Sea region points", ["Point"])
    if lakes_geo:
        validate_geometry_kinds(lakes_geo, "Lakes", ["Polygon", "MultiPolygon"])
    if borders_geo:
        validate_geometry_kinds(borders_geo, "Borders", ["Polygon", "MultiPolygon"])
    if oceans_geo:
        validate_geometry_kinds(oceans_geo, "Oceans", ["Polygon", "MultiPolygon"])
    if rivers_geo:
        validate_geometry_kinds(rivers_geo, "Rivers", ["LineString", "MultiLineString", "Polygon", "MultiPolygon"])
    river_items = [(proj.to_work(geom), props) for geom, props in line_geometries(rivers_geo)] if rivers_geo else []

    report(progress, 8, "validating-inputs", "Checking point and polygon collections")
    city_points = point_features(cities_geo, "cities", "city")
    sea_points = point_features(sea_geo, "sea", "sea") if sea_geo else []
    for point in city_points + sea_points:
        point["geom"] = proj.to_work(point["geom"])
    if sea_points and not oceans_geo:
        raise ValueError("Sea region points were uploaded but oceans polygon is missing.")

    report(progress, 18, "preparing-land-mask", "Combining land polygons")
    land_mask = proj.to_work(preclip(merge_polygons(land_geo, "land"), bbox_ll))
    lakes_mask = proj.to_work(preclip(merge_polygons(lakes_geo, "lakes"), bbox_ll)) if lakes_geo else None
    oceans_mask = proj.to_work(preclip(merge_polygons(oceans_geo, "oceans"), bbox_ll)) if oceans_geo else None
    ocean_components = split_components(oceans_mask, "sea-body")

    diagnostics = {
        "unmatchedCities": [],
        "emptyCountriesDetected": [],
        "emptyCountryPolicies": [],
        "lloydEnabled": bool(options.get("lloydEnabled")),
        "lloydIterations": int(options.get("lloydIterations", 1)) if options.get("lloydEnabled") else 0,
        "riverInfluenceEnabled": bool(options.get("riverInfluenceEnabled")) and bool(river_items),
        "riverFeatureCount": len(river_items),
        "lakesMaskEnabled": bool(lakes_mask and not lakes_mask.is_empty),
        "seaBodyCount": len(ocean_components),
        "seaAutoSeeded": not sea_points,
        "smoothingEnabled": bool(options.get("smoothingEnabled")),
        "smoothingMethod": options.get("smoothingMethod") if options.get("smoothingEnabled") else None,
    }
    gen_options = {**options, "riverFeatures": river_items}
    land_regions = []
    synthetic_lakes = []
    empty_lands = []
    merged_empty = []

    if options.get("useBorders"):
        report(progress, 36, "preparing-borders", "Grouping country border polygons")
        countries, alias_map = build_country_catalog(borders_geo, bbox_ll, proj)
        buckets = {}
        represented = set()
        for point in city_points:
            country = find_country_for_city(point["properties"], alias_map)
            if not country:
                # No property match: fall back to the border polygon that contains the city.
                country = next((c for c in countries if c["mask"].contains(point["geom"])), None)
                if country:
                    warnings.push("border_match_by_location", "A city had no matching country property; it was assigned by location.", {"city": point["properties"].get("name", "Unknown"), "country": country["name"]})
            if not country:
                unmatched = {"city": point["properties"].get("name", "Unknown"), "country": point["properties"].get("country", "")}
                diagnostics["unmatchedCities"].append(unmatched)
                warnings.push("border_match_missing", "A city did not match any border polygon.", unmatched)
                continue
            buckets.setdefault(country["key"], {"country": country, "cities": []})["cities"].append(point)
            represented.add(country["key"])
        total = max(1, sum(len(v["cities"]) for v in buckets.values()))
        done = 0
        for entry in buckets.values():
            country = entry["country"]
            seeds = entry["cities"]
            local_land = clean_geom(land_mask.intersection(box(*expand_bounds(country["bbox"], 0.1))))
            local_lakes = clean_geom(lakes_mask.intersection(box(*expand_bounds(country["bbox"], 0.1)))) if lakes_mask else None
            allowed = clean_geom(country["mask"].intersection(local_land))
            if options.get("lloydEnabled") and len(seeds) > 1:
                seeds = relax_points(seeds, allowed, expand_bounds(country["bbox"], 0.35), options.get("lloydIterations", 1))
            cells = finite_voronoi_polygons([p["geom"] for p in seeds], expand_bounds(country["bbox"], 0.35))
            for seed, cell in zip(seeds, cells):
                geom = clip_region(cell if len(seeds) > 1 else country["mask"], country["mask"], local_land, local_lakes, gen_options, warnings, {"city": seed["properties"].get("name", ""), "country": country["name"]})
                if geom:
                    props = build_region_properties(seed["properties"], key_factory, include_main_city=True, default_main_city=False)
                    props["__sourceId"] = seed["properties"].get("__sourceId")
                    props["regionType"] = "land"
                    land_regions.append({"geom": geom, "properties": props})
                done += 1
                report(progress, 42 + (done / total) * 42, "building-country-voronoi", f"Processed {done}/{total} cities")
        empty = [c for c in countries if c["key"] not in represented]
        diagnostics["emptyCountriesDetected"] = [c["name"] for c in empty]
        overrides = {normalize_value(k): v for k, v in (options.get("emptyCountryOverrides") or {}).items() if v}
        default_policy = options.get("emptyCountryPolicyDefault") or EMPTY_COUNTRY_POLICIES["empty"]
        represented_countries = [c for c in countries if c["key"] in represented]
        for country in empty:
            policy = overrides.get(country["key"]) or overrides.get(normalize_value(country["name"])) or default_policy
            result = {"country": country["name"], "policy": policy, "target": None}
            if policy == EMPTY_COUNTRY_POLICIES["merge"] and represented_countries:
                target = min(represented_countries, key=lambda c: (country["centroid"].distance(c["centroid"]), c["area"]))
                result["target"] = target["name"]
                geom = clip_region(country["mask"], None, land_mask, lakes_mask, gen_options, warnings, {"country": country["name"]})
                if geom:
                    props = build_region_properties({"name": f"{country['name']} (Merged)", "country": target["name"], "merged_from": country["name"], "synthetic": True, "resolution": policy}, key_factory, default_main_city=False)
                    props["regionType"] = "land"
                    land_regions.append({"geom": geom, "properties": props})
                    merged_empty.append(feature(geom, props))
            elif policy == EMPTY_COUNTRY_POLICIES["lake"]:
                lake = feature(country["mask"], {"country": country["name"], "synthetic": True, "resolution": policy})
                synthetic_lakes.append(lake)
                lakes_mask = clean_geom(unary_union([g for g in [lakes_mask, country["mask"]] if g is not None]))
            else:
                empty_lands.append(feature(country["mask"], {"country": country["name"], "synthetic": True, "resolution": EMPTY_COUNTRY_POLICIES["empty"]}))
            diagnostics["emptyCountryPolicies"].append(result)
    else:
        seeds = city_points
        if options.get("lloydEnabled") and len(seeds) > 1:
            report(progress, 40, "lloyd-relaxation", "Relaxing global Voronoi seeds")
            seeds = relax_points(seeds, land_mask, bbox, options.get("lloydIterations", 1))
        cells = finite_voronoi_polygons([p["geom"] for p in seeds], bbox)
        for index, (seed, cell) in enumerate(zip(seeds, cells), start=1):
            geom = clip_region(cell, None, land_mask, lakes_mask, gen_options, warnings, {"city": seed["properties"].get("name", ""), "country": seed["properties"].get("country", "")})
            if geom:
                props = build_region_properties(seed["properties"], key_factory, include_main_city=True, default_main_city=False)
                props["__sourceId"] = seed["properties"].get("__sourceId")
                props["regionType"] = "land"
                land_regions.append({"geom": geom, "properties": props})
            report(progress, 54 + (index / len(seeds)) * 38, "clipping-provinces", f"Processed {index}/{len(seeds)} cells")

    land_areas = [r["geom"].area for r in land_regions if not r["geom"].is_empty]
    sea_target_area = median(land_areas) if land_areas else None
    sea_regions = generate_open_water(sea_points, oceans_mask, ocean_components, gen_options, warnings, key_factory, progress, sea_target_area) if oceans_mask else []
    diagnostics["landRegionCount"] = len(land_regions)
    diagnostics["seaRegionCount"] = len(sea_regions)
    diagnostics["lakesMaskEnabled"] = bool(lakes_mask and not lakes_mask.is_empty)

    report(progress, 94, "building-package", "Building simulation package outputs")
    package = build_package(options.get("outPath") or DEFAULT_INPUTS["out"], bbox, land_regions, sea_regions, city_points, sea_points, river_items, options, proj)
    # The preview (and the in-memory result) stays in lon/lat so it overlays the input layers.
    def preview(collection):
        return transform_collection(collection, proj.to_lonlat) if proj.projected else collection

    output = preview(package["provinces"])
    report(progress, 100, "completed", f"Wrote {len(output['features'])} regions")
    return {
        "bbox": bbox_ll,
        "outPath": str(Path(options.get("outPath") or DEFAULT_INPUTS["out"]).resolve()),
        "featureCount": len(output["features"]),
        "output": output,
        "package": {"paths": package["packagePaths"], "metadata": package["metadata"]},
        "warnings": warnings.warnings,
        "diagnostics": diagnostics,
        "layers": {key: preview(value) for key, value in {
            "generatedCities": package["cities"],
            "movementNodes": package["movementNodes"],
            "movementEdges": package["movementEdges"],
            "railNodes": package["railNodes"],
            "railEdges": package["railEdges"],
            "seaRegions": package["seaRegions"],
            "rivers": feature_collection([feature(geom, {**props, "layerType": "reference", "source": "rivers"}) for geom, props in river_items]),
            "oceanMask": feature_collection([feature(c["mask"], {"layerType": "mask", "regionType": "sea_mask", "source": "oceans", "seaBodyId": c["id"], "seaBodyIndex": c["index"]}) for c in ocean_components]),
            "lakesMask": feature_collection([feature(lakes_mask, {"layerType": "mask", "regionType": "lake_mask", "source": "lakes"})] if lakes_mask and not lakes_mask.is_empty else []),
            "syntheticLakes": feature_collection(synthetic_lakes),
            "emptyLands": feature_collection(empty_lands),
            "mergedEmptyCountries": feature_collection(merged_empty),
        }.items()},
    }


def zip_package(package_paths, archive_path):
    archive_path = Path(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    base = Path(package_paths["dir"]).name or "map-package"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for key, value in package_paths.items():
            if key == "dir":
                continue
            path = Path(value)
            if path.exists():
                archive.write(path, f"{base}/{path.name}")
    return archive_path
