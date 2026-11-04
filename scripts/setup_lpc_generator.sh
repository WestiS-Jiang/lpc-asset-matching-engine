#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GENERATOR_DIR="$ROOT_DIR/generator"
REPOSITORY_URL="https://github.com/LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator.git"
PINNED_COMMIT="2b75dfec03"

if [[ -d "$GENERATOR_DIR/.git" ]]; then
  echo "LPC generator already exists at $GENERATOR_DIR"
  exit 0
fi

if [[ -e "$GENERATOR_DIR" ]]; then
  echo "Refusing to overwrite existing non-Git path: $GENERATOR_DIR" >&2
  exit 1
fi

git clone --filter=blob:none --no-checkout "$REPOSITORY_URL" "$GENERATOR_DIR"
git -C "$GENERATOR_DIR" fetch --depth 1 origin "$PINNED_COMMIT"
git -C "$GENERATOR_DIR" checkout --detach FETCH_HEAD

echo "Installed LPC generator at commit $(git -C "$GENERATOR_DIR" rev-parse --short HEAD)"
echo "Run: python scanner.py"

