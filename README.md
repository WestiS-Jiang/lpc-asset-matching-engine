# LPC Asset Matching Engine

An AI-assisted game-resource production tool that maps natural-language character descriptions to reusable Liberated Pixel Cup (LPC) layers.

The stable product path is:

```text
character description
  -> asset definition scan
  -> semantic tags and local vector index
  -> slot-aware candidate ranking
  -> Body / Hair / Armor / Weapons selection
  -> source and compatibility inspection
  -> layered browser preview
```

Image generation and automatic spritesheet registration exist as experimental code paths, but they are not the primary demonstration flow because their output quality and animation compatibility are not consistently stable.

## Why this project exists

Game teams often have a large asset library but no reliable way to answer questions such as:

- Which existing layers best match a character description?
- Does a candidate support the required body type and animations?
- Which request can be fulfilled from the library, and which part is missing?
- Can the result be inspected before expensive generation work begins?

This project turns the LPC repository into a searchable asset system rather than treating it as a directory of PNG files.

## Core components

| Component | Responsibility |
| --- | --- |
| `scanner.py` | Parses LPC sheet definitions, animation coverage, body support, layer order, variants, colors, and semantic tags. |
| `lpc_vector_index.py` | Builds and queries a lightweight local TF-IDF-style index over asset metadata. |
| `main.py` | Exposes FastAPI endpoints for analysis, capability reporting, lookup, preview support, and experimental generation. |
| `frontend_lab/` | Visual inspection page for prompt results, layer provenance, and composite previews. |
| `manifest.json` | Compact category-to-item mapping generated from LPC definitions. |
| `asset_catalog.json` | Auditable catalog with item metadata, warnings, and capability statistics. |

## Operating modes

### Catalog-only mode

The GitHub package includes a precomputed catalog and vector index. Without the large LPC checkout, the backend can still:

- load the asset taxonomy;
- rank and validate item IDs;
- expose capability statistics;
- demonstrate the prompt-to-layer workflow;
- run the test suite without downloading gigabytes of art assets.

Real sprite images are unavailable in this mode.

### Full LPC mode

Install the pinned upstream generator:

```bash
./scripts/setup_lpc_generator.sh
python scanner.py
python lpc_vector_index.py
```

This downloads the LPC definitions and spritesheets directly from the upstream project. The checkout is intentionally ignored by Git because it is large and has separate attribution obligations.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp service_config.example.json service_config.json
.venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open:

- API documentation: `http://127.0.0.1:8000/docs`
- Frontend lab: `http://127.0.0.1:8000/frontend_lab/index.html`

For optional background removal and experimental image processing:

```bash
.venv/bin/pip install -r requirements-optional.txt
```

## Configuration

Never commit `service_config.json`. Configure providers using that ignored local file or environment variables:

- `LLM_RELAY_URL`
- `LLM_RELAY_API_KEY`
- `LLM_RELAY_MODEL`
- `IMAGE_RELAY_URL`
- `IMAGE_RELAY_API_KEY`
- `IMAGE_RELAY_MODEL`
- `GEN_MODE_DEFAULT`
- `GEN_MAX_GENERATION_TASKS`

The default runtime keeps generation disabled.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover catalog scanning, semantic matching, fallback behavior, layer compatibility, image preprocessing, API responses, and catalog-only operation.

## Interview framing

The project is best presented as an asset retrieval and compatibility system:

1. Convert a heterogeneous game-art repository into structured metadata.
2. Enrich items with semantic, animation, body-type, color, and equipment tags.
3. Combine deterministic slot constraints with local semantic ranking and optional LLM interpretation.
4. Return traceable layer selections and identify missing capability before generation.
5. Preserve an experimental generation boundary without making unstable registration the core product claim.

## Third-party assets

This repository does not redistribute the full LPC asset library. See `THIRD_PARTY_NOTICES.md` and the upstream generator's `CREDITS.csv` before distributing any generated or composed sprite output.

