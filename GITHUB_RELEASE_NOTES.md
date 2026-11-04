# GitHub release notes

## Suggested repository name

`lpc-asset-matching-engine`

## Included

- FastAPI asset analysis and capability-report endpoints
- LPC definition scanner and semantic asset catalog
- Local vector index for natural-language asset retrieval
- Lightweight browser lab for prompt-to-layer inspection
- Tests for matching, fallback, image processing, and API behavior
- Precomputed, path-sanitized catalog data for catalog-only demonstrations

## Intentionally excluded

- Real API keys and `service_config.json`
- Python virtual environments, IDE metadata, caches, and generated outputs
- The 1.3 GB LPC spritesheet tree and 2 GB nested Git history
- Custom generated assets and unstable spritesheet registration results

## External dependency boundary

The full visual preview depends on the Universal LPC Spritesheet Character Generator. The repository runs in catalog-only mode without it. Use `scripts/setup_lpc_generator.sh` to install the pinned upstream version locally.

