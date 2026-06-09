# Meric's Game Tools - Map Generator

Meric's Game Tools - Map Generator is a desktop workbench for creating Meric's Game Tools map packages. It lets you choose input GeoJSON layers, tune generation options, preview layers, generate provinces and sea regions, and export a complete package.

Repository: <https://github.com/merchizm/mgt_map_generator>

## Installation

```bash
cd mgt_map_gen_py
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Python 3.10+ is recommended.

## Desktop App

```bash
python -m mgt_map_gen_py
```

When installed as a package:

```bash
mgt-map-gen
```

The app includes file inputs, generation controls, map/code preview, layer list, package details, warnings, diagnostics, a feature inspector, bbox drawing from the map, and debounced live preview processing.

## Qlementine Theme

The app uses the real Qlementine Qt style when its local style plugin is built. Build it once with:

```bash
cmake -S qlementine_style_plugin -B build/qlementine-style-plugin
cmake --build build/qlementine-style-plugin
```

After that, `python -m mgt_map_gen_py` loads the `Qlementine` style from `build/qlementine-style-plugin/styles` at startup.