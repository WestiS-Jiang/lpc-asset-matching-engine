import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
GENERATOR_DIR = ROOT_DIR / "generator"
DEFAULT_DEFINITIONS_ROOT = GENERATOR_DIR / "sheet_definitions"
DEFAULT_SPRITES_ROOT = GENERATOR_DIR / "spritesheets"
DEFAULT_MANIFEST_PATH = ROOT_DIR / "manifest.json"
DEFAULT_ASSET_CATALOG_PATH = ROOT_DIR / "asset_catalog.json"

LAYER_META_KEYS = {
    "zPos",
    "custom_animation",
    "custom_frame_size",
    "opacity",
    "rotation",
    "debug_label",
}
CORE_BODY_KEYS = ("male", "female", "teen", "child", "muscular", "pregnant")
COLOR_TOKENS = {
    "black",
    "white",
    "gray",
    "grey",
    "blue",
    "cyan",
    "navy",
    "sky",
    "teal",
    "green",
    "forest",
    "olive",
    "red",
    "darkred",
    "maroon",
    "pink",
    "rose",
    "purple",
    "violet",
    "lavender",
    "yellow",
    "gold",
    "orange",
    "brown",
    "tan",
    "walnut",
    "charcoal",
    "leather",
    "silver",
    "platinum",
}
WEAPON_TOKEN_TAGS = {
    "sword": "weapon.sword",
    "dagger": "weapon.dagger",
    "axe": "weapon.axe",
    "mace": "weapon.mace",
    "hammer": "weapon.hammer",
    "club": "weapon.club",
    "staff": "weapon.staff",
    "spear": "weapon.spear",
    "trident": "weapon.trident",
    "bow": "weapon.bow",
    "crossbow": "weapon.crossbow",
    "rifle": "weapon.firearm",
    "gun": "weapon.firearm",
    "firearm": "weapon.firearm",
    "musket": "weapon.firearm",
    "wand": "weapon.magic",
    "orb": "weapon.magic",
}


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _count_layers(definition: dict[str, Any]) -> int:
    count = 0
    for idx in range(1, 20):
        if f"layer_{idx}" in definition and isinstance(definition[f"layer_{idx}"], dict):
            count += 1
        else:
            break
    return count


def _zpos_signature(definition: dict[str, Any]) -> tuple[int, ...]:
    values: list[int] = []
    for idx in range(1, 20):
        layer = definition.get(f"layer_{idx}")
        if not isinstance(layer, dict):
            break
        try:
            zpos = int(layer.get("zPos", 100))
        except (TypeError, ValueError):
            zpos = 100
        values.append(zpos)
    return tuple(values)


def _collect_body_support(definition: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    for idx in range(1, 20):
        layer = definition.get(f"layer_{idx}")
        if not isinstance(layer, dict):
            break
        for body_key in CORE_BODY_KEYS:
            if layer.get(body_key):
                keys.add(body_key)
    return sorted(keys)


def _normalize_animation(animation_name: str) -> str:
    normalized = str(animation_name or "").strip().lower()
    if not normalized:
        return normalized
    if normalized in {"1h_slash", "1h_halfslash", "1h_backslash"}:
        return "melee_slash_1h"
    if "shoot" in normalized:
        return "ranged_shoot"
    if "thrust" in normalized:
        return "melee_thrust"
    if "slash" in normalized:
        return "melee_slash"
    return normalized


def _collect_variant_tokens(definition: dict[str, Any]) -> list[str]:
    variants = definition.get("variants")
    if not isinstance(variants, list):
        return []
    tokens: set[str] = set()
    for value in variants:
        if not isinstance(value, str):
            continue
        for token in _tokenize(value):
            if token:
                tokens.add(token)
    return sorted(tokens)


def _collect_recolor_tokens(definition: dict[str, Any]) -> list[str]:
    recolors = definition.get("recolors")
    if not isinstance(recolors, list):
        return []
    tokens: set[str] = set()
    for recolor in recolors:
        if not isinstance(recolor, dict):
            continue
        variants = recolor.get("variants")
        if not isinstance(variants, list):
            continue
        for value in variants:
            if not isinstance(value, str):
                continue
            for token in _tokenize(value):
                if token:
                    tokens.add(token)
    return sorted(tokens)


def _infer_semantic_tags(
    *,
    item_id: str,
    display_name: str,
    primary_category: str,
    type_name: str | None,
    path_parts: list[str],
    animations: list[str],
    variant_tokens: list[str],
    recolor_tokens: list[str],
) -> list[str]:
    tags: set[str] = set()
    tags.add(f"category.{primary_category}")
    if type_name:
        tags.add(f"type.{str(type_name).lower()}")
    if path_parts:
        tags.add(f"domain.{path_parts[0]}")

    lexical_tokens = set(_tokenize(f"{item_id} {display_name} {' '.join(path_parts)} {type_name or ''}"))
    if primary_category in {"torso", "legs", "feet", "armor"}:
        tags.add("role.outfit")
    if primary_category == "feet":
        tags.add("role.feet")
    if primary_category == "legs":
        tags.add("role.legs")

    if any(token in lexical_tokens for token in {"dress", "gown", "kimono", "robe"}):
        tags.add("outfit.dress")
    if any(token in lexical_tokens for token in {"skirt", "overskirt"}):
        tags.add("outfit.skirt")
    if any(token in lexical_tokens for token in {"shirt", "jacket", "coat", "blouse"}):
        tags.add("outfit.top")
    if any(token in lexical_tokens for token in {"pants", "trousers", "shorts", "leggings"}):
        tags.add("outfit.bottom")
    if any(token in lexical_tokens for token in {"shoe", "shoes", "boot", "boots", "sandals", "slippers", "sneaker"}):
        tags.add("outfit.footwear")

    if primary_category == "weapons":
        tags.add("role.weapon")
        if "ranged" in lexical_tokens:
            tags.add("weapon.ranged")
        if any(token in lexical_tokens for token in {"magic", "spell", "orb", "wand"}):
            tags.add("weapon.magic")
        if any(token in lexical_tokens for token in {"shield"}):
            tags.add("weapon.shield")
        if any(token in lexical_tokens for token in {"sword", "axe", "dagger", "mace", "hammer", "spear", "staff", "trident"}):
            tags.add("weapon.melee")
        if any(token in lexical_tokens for token in {"bow", "crossbow", "rifle", "gun", "firearm", "musket"}):
            tags.add("weapon.ranged")
        for token, mapped in WEAPON_TOKEN_TAGS.items():
            if token in lexical_tokens:
                tags.add(mapped)

    if primary_category == "armor":
        tags.add("role.armor")
        if any(token in lexical_tokens for token in {"plate", "chain", "mail"}):
            tags.add("armor.heavy")
        if any(token in lexical_tokens for token in {"leather", "cloth"}):
            tags.add("armor.light")

    if primary_category == "hair":
        tags.add("role.hair")
    if primary_category == "body":
        tags.add("role.body")
    if "hat" in lexical_tokens or "cap" in lexical_tokens or "helmet" in lexical_tokens:
        tags.add("role.headwear")
    if "beard" in lexical_tokens or "mustache" in lexical_tokens:
        tags.add("role.facial_hair")

    for animation in animations:
        tags.add(f"anim.{_normalize_animation(animation)}")
    for color_token in sorted(set(variant_tokens + recolor_tokens)):
        if color_token in COLOR_TOKENS:
            tags.add(f"color.{color_token}")

    return sorted(tags)


def _extract_layer_paths(definition: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for idx in range(1, 20):
        layer = definition.get(f"layer_{idx}")
        if not isinstance(layer, dict):
            break
        for key, value in layer.items():
            if key in LAYER_META_KEYS:
                continue
            if isinstance(value, str) and value:
                paths.append(value)
    return paths


def _contains_template_variable(path_text: str) -> bool:
    return "${" in path_text


def _compute_common_prefix(paths: list[str]) -> str:
    if not paths:
        return ""
    split_paths = [Path(path_text.strip("/")).parts for path_text in paths if path_text]
    if not split_paths:
        return ""
    min_len = min(len(parts) for parts in split_paths)
    common: list[str] = []
    for idx in range(min_len):
        token = split_paths[0][idx]
        if all(parts[idx] == token for parts in split_paths):
            common.append(token)
        else:
            break
    return "/".join(common)


def _normalize_primary_category(
    path_parts: list[str], type_name: str | None, item_id: str
) -> str:
    top = path_parts[0].lower() if path_parts else "other"
    type_name_normalized = (type_name or "").lower()
    item_id_normalized = item_id.lower()

    if top == "weapons" or type_name_normalized in {
        "weapon",
        "shield",
        "shield_trim",
        "shield_pattern",
        "shield_paint",
        "ammo",
    }:
        return "weapons"

    if top == "torso" and len(path_parts) > 1 and path_parts[1].lower() == "armour":
        return "armor"
    if type_name_normalized == "armour":
        return "armor"
    if "armour" in item_id_normalized or "armor" in item_id_normalized:
        return "armor"

    if top == "hair" or type_name_normalized in {"hair", "beard", "mustache"}:
        return "hair"

    if top == "body" or type_name_normalized == "body":
        return "body"

    return top


def _build_manifest_categories(
    path_parts: list[str], primary_category: str, type_name: str | None
) -> set[str]:
    categories = {primary_category}
    if path_parts:
        categories.add(path_parts[0].lower())
    if type_name:
        categories.add(type_name.lower())
    return {category for category in categories if category}


def _validate_layer_paths(
    *,
    item_id: str,
    definition_file: Path,
    layer_paths: list[str],
    sprites_root: Path,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for path_text in layer_paths:
        if _contains_template_variable(path_text):
            warnings.append(
                {
                    "item_id": item_id,
                    "definition_file": str(definition_file),
                    "path": path_text,
                    "kind": "template_variable",
                }
            )
            continue

        candidate = sprites_root / path_text.strip("/")
        if not candidate.exists():
            warnings.append(
                {
                    "item_id": item_id,
                    "definition_file": str(definition_file),
                    "path": path_text,
                    "kind": "missing_path",
                }
            )
    return warnings


def scan_sheet_definitions(
    definitions_root: Path | str = DEFAULT_DEFINITIONS_ROOT,
    sprites_root: Path | str = DEFAULT_SPRITES_ROOT,
) -> dict[str, Any]:
    definitions_root = Path(definitions_root)
    sprites_root = Path(sprites_root)

    if definitions_root == DEFAULT_DEFINITIONS_ROOT and not definitions_root.exists():
        if not DEFAULT_ASSET_CATALOG_PATH.exists():
            raise FileNotFoundError(
                "LPC definitions are missing and no precomputed asset catalog is available."
            )
        catalog = json.loads(DEFAULT_ASSET_CATALOG_PATH.read_text(encoding="utf-8"))
        summary = dict(catalog.get("summary", {}))
        summary["catalog_mode"] = True
        catalog["summary"] = summary
        return catalog

    manifest_map: dict[str, set[str]] = {}
    items_by_id: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, str]] = []
    top_folder_counter: Counter[str] = Counter()
    type_name_counter: Counter[str] = Counter()
    animation_counter: Counter[str] = Counter()
    body_support_counter: Counter[str] = Counter()
    semantic_tag_counter: Counter[str] = Counter()
    color_token_counter: Counter[str] = Counter()

    for file_path in sorted(definitions_root.rglob("*.json")):
        if file_path.name.startswith("meta_"):
            continue

        try:
            definition = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warnings.append(
                {
                    "item_id": file_path.stem,
                    "definition_file": str(file_path),
                    "path": str(file_path),
                    "kind": "invalid_json",
                }
            )
            continue

        if definition.get("ignore") is True:
            continue

        item_id = file_path.stem
        relative_path = file_path.relative_to(definitions_root)
        folder_parts = [part.lower() for part in relative_path.parts[:-1]]
        type_name = definition.get("type_name")
        primary_category = _normalize_primary_category(folder_parts, type_name, item_id)
        manifest_categories = _build_manifest_categories(folder_parts, primary_category, type_name)
        if folder_parts:
            top_folder_counter[folder_parts[0]] += 1
        type_name_counter[str(type_name or "null").lower()] += 1

        layer_paths = _extract_layer_paths(definition)
        warnings.extend(
            _validate_layer_paths(
                item_id=item_id,
                definition_file=file_path,
                layer_paths=layer_paths,
                sprites_root=sprites_root,
            )
        )

        template_base_prefix = _compute_common_prefix(
            [path_text for path_text in layer_paths if not _contains_template_variable(path_text)]
        )
        animations = definition.get("animations", [])
        if not isinstance(animations, list):
            animations = []
        normalized_animations = sorted({_normalize_animation(str(anim)) for anim in animations if str(anim).strip()})
        for anim in normalized_animations:
            animation_counter[anim] += 1
        body_support = _collect_body_support(definition)
        for body_key in body_support:
            body_support_counter[body_key] += 1
        variant_tokens = _collect_variant_tokens(definition)
        recolor_tokens = _collect_recolor_tokens(definition)
        for token in set(variant_tokens + recolor_tokens):
            if token in COLOR_TOKENS:
                color_token_counter[token] += 1
        semantic_tags = _infer_semantic_tags(
            item_id=item_id,
            display_name=str(definition.get("name") or item_id),
            primary_category=primary_category,
            type_name=type_name if isinstance(type_name, str) else None,
            path_parts=folder_parts,
            animations=normalized_animations,
            variant_tokens=variant_tokens,
            recolor_tokens=recolor_tokens,
        )
        for tag in semantic_tags:
            semantic_tag_counter[tag] += 1

        item_record = {
            "item_id": item_id,
            "display_name": definition.get("name") or item_id,
            "type_name": type_name,
            "primary_category": primary_category,
            "manifest_categories": sorted(manifest_categories),
            "definition_file": str(file_path),
            "relative_definition_file": str(file_path.relative_to(ROOT_DIR)),
            "path_parts": folder_parts,
            "json_path": definition.get("path", []),
            "is_standard_template": bool(definition.get("is_standard_template", False)),
            "layer_count": _count_layers(definition),
            "zpos_signature": _zpos_signature(definition),
            "animations": animations,
            "animations_normalized": normalized_animations,
            "supports_body_types": body_support,
            "variant_tokens": variant_tokens,
            "recolor_tokens": recolor_tokens,
            "semantic_tags": semantic_tags,
            "template_base_prefix": template_base_prefix,
            "search_text": " ".join(
                _tokenize(f"{item_id} {definition.get('name', '')} {type_name or ''} {' '.join(folder_parts)}")
            ),
        }
        items_by_id[item_id] = item_record

        for category in manifest_categories:
            manifest_map.setdefault(category, set()).add(item_id)

    manifest = {
        category: sorted(values)
        for category, values in sorted(manifest_map.items(), key=lambda pair: pair[0])
    }

    return {
        "manifest": manifest,
        "items_by_id": items_by_id,
        "warnings": warnings,
        "summary": {
            "total_items": len(items_by_id),
            "total_categories": len(manifest),
            "total_warnings": len(warnings),
            "top_folders": top_folder_counter.most_common(20),
            "top_type_names": type_name_counter.most_common(40),
            "top_animations": animation_counter.most_common(40),
            "body_type_coverage": sorted(body_support_counter.items()),
            "top_semantic_tags": semantic_tag_counter.most_common(80),
            "top_color_tokens": color_token_counter.most_common(40),
        },
    }


def write_manifest(
    output_path: Path | str = DEFAULT_MANIFEST_PATH,
    definitions_root: Path | str = DEFAULT_DEFINITIONS_ROOT,
    sprites_root: Path | str = DEFAULT_SPRITES_ROOT,
) -> dict[str, Any]:
    output_path = Path(output_path)
    result = scan_sheet_definitions(definitions_root=definitions_root, sprites_root=sprites_root)
    output_path.write_text(
        json.dumps(result["manifest"], indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def write_asset_catalog(
    output_path: Path | str = DEFAULT_ASSET_CATALOG_PATH,
    scan_result: dict[str, Any] | None = None,
    definitions_root: Path | str = DEFAULT_DEFINITIONS_ROOT,
    sprites_root: Path | str = DEFAULT_SPRITES_ROOT,
) -> dict[str, Any]:
    output_path = Path(output_path)
    result = scan_result or scan_sheet_definitions(definitions_root=definitions_root, sprites_root=sprites_root)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    scan_result = write_manifest()
    write_asset_catalog(scan_result=scan_result)
    print(
        json.dumps(
            {
                "manifest_path": str(DEFAULT_MANIFEST_PATH),
                "asset_catalog_path": str(DEFAULT_ASSET_CATALOG_PATH),
                "summary": scan_result["summary"],
            },
            ensure_ascii=True,
        )
    )
