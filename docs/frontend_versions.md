# Frontend versions (v1 / v2)

- `v1`: existing templates under `templates/`.
- `v2`: refreshed UI templates under `templates_v2/`.

## Build commands

```bash
# Build both versions under dist/v1 and dist/v2 (default)
python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --output-dir dist --version all

# Build only v1
python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --output-dir dist --version v1

# Build only v2
python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --output-dir dist --version v2
```

## Version switching by URL

- `.../tatemono-map/v1/index.html`
- `.../tatemono-map/v2/index.html`

## LINE CTA configuration

Set with environment variables (or `.env`):

- `TATEMONO_MAP_LINE_CTA_URL` (default: `https://lin.ee/Y0NvwKe`)
- `TATEMONO_MAP_LINE_DEEP_LINK_URL` (default: `line://ti/p/@055wdvuq`)

The v2 detail page renders a single LINE button that keeps `href` on the universal link and attempts deep-link first via inline JavaScript, then falls back after 700ms.
