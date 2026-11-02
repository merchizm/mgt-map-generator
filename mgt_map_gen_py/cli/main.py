import argparse

from ..core.generator import generate_provinces
from ..core.geo_utils import EMPTY_COUNTRY_POLICIES


def build_parser():
    parser = argparse.ArgumentParser(description="Generate a map package from GeoJSON layers.")
    parser.add_argument("--cities", required=True)
    parser.add_argument("--land", required=True)
    parser.add_argument("--out", default="provinces.geojson")
    parser.add_argument("--lakes")
    parser.add_argument("--borders")
    parser.add_argument("--oceans")
    parser.add_argument("--sea-cities")
    parser.add_argument("--rivers")
    parser.add_argument("--use-borders", action="store_true")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("MIN_LNG", "MIN_LAT", "MAX_LNG", "MAX_LAT"))

    gen = parser.add_argument_group("generation")
    gen.add_argument("--lloyd", action="store_true", help="Enable Lloyd relaxation of seed points")
    gen.add_argument("--lloyd-iterations", type=int, default=1)
    gen.add_argument("--river-influence", action="store_true")
    gen.add_argument("--river-strength", type=float, default=0.32)
    gen.add_argument("--smoothing", action="store_true", help="Enable edge smoothing")
    gen.add_argument("--smoothing-method", choices=["chaikin", "bezier"], default="chaikin")
    gen.add_argument("--smoothing-iterations", type=int, default=1)
    gen.add_argument("--smoothing-strength", type=float, default=0.24)
    gen.add_argument("--empty-country-policy", choices=sorted(EMPTY_COUNTRY_POLICIES), default="empty",
                     help="What to do with countries that have no cities (border mode)")

    gen.add_argument("--sea-cell-scale", type=float, default=3.0,
                     help="Auto-generated sea regions are this many times the median land province area (default 3)")
    gen.add_argument("--sea-seed", type=int, default=1, help="Random seed for auto-generated sea regions")

    gen.add_argument("--projection", choices=["lcc", "lonlat"], default="lcc",
                     help="Coordinate system of the written package: Lambert conformal conic in km (default) or raw lon/lat")

    pkg = parser.add_argument_group("package metadata")
    pkg.add_argument("--package-dir")
    pkg.add_argument("--map-key")
    pkg.add_argument("--map-name")
    pkg.add_argument("--map-version")
    pkg.add_argument("--world-width", type=float)
    pkg.add_argument("--world-height", type=float)
    return parser


def main():
    args = build_parser().parse_args()
    result = generate_provinces({
        "citiesPath": args.cities,
        "landPath": args.land,
        "outPath": args.out,
        "lakesPath": args.lakes,
        "bordersPath": args.borders,
        "oceansPath": args.oceans,
        "seaCitiesPath": args.sea_cities,
        "riversPath": args.rivers,
        "useBorders": args.use_borders,
        "bbox": args.bbox,
        "lloydEnabled": args.lloyd,
        "lloydIterations": args.lloyd_iterations,
        "riverInfluenceEnabled": args.river_influence,
        "riverInfluenceStrength": args.river_strength,
        "smoothingEnabled": args.smoothing,
        "smoothingMethod": args.smoothing_method,
        "smoothingIterations": args.smoothing_iterations,
        "smoothingStrength": args.smoothing_strength,
        "emptyCountryPolicyDefault": EMPTY_COUNTRY_POLICIES[args.empty_country_policy],
        "seaAutoCellScale": args.sea_cell_scale,
        "seaSeed": args.sea_seed,
        "packageDir": args.package_dir,
        "mapKey": args.map_key,
        "mapName": args.map_name,
        "mapVersion": args.map_version,
        "projectionMode": args.projection,
        "worldWidth": args.world_width,
        "worldHeight": args.world_height,
        "onProgress": lambda p: print(f"[{p['percent']}%] {p['stage']} - {p.get('detail', '')}"),
    })
    for warning in result["warnings"]:
        print(f"warning [{warning['code']}]: {warning['message']} {warning['context']}")
    print(f"Wrote {result['featureCount']} regions to {result['outPath']}")


if __name__ == "__main__":
    main()
