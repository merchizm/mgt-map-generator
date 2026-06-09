import argparse

from ..core.generator import generate_provinces


def main():
    parser = argparse.ArgumentParser()
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
    args = parser.parse_args()
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
        "onProgress": lambda p: print(f"[{p['percent']}%] {p['stage']} - {p.get('detail', '')}"),
    })
    print(f"Wrote {result['featureCount']} regions to {result['outPath']}")


if __name__ == "__main__":
    main()
