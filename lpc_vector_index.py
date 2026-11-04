import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_VECTOR_INDEX_PATH = ROOT_DIR / "lpc_vector_index.json"


def _tokenize(text: str) -> list[str]:
    normalized = str(text or "").lower()
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            tokens.append(token)
            if len(token) > 1:
                for idx in range(len(token) - 1):
                    tokens.append(token[idx : idx + 2])
        else:
            tokens.append(token)
    return [token for token in tokens if token]


def _is_custom_item(item: dict[str, Any]) -> bool:
    path_parts = [str(part).lower() for part in item.get("path_parts", [])]
    definition_file = str(item.get("definition_file", "")).replace("\\", "/").lower()
    return "custom" in path_parts or "/custom/" in definition_file


def _source_category(item: dict[str, Any]) -> str:
    path_parts = item.get("path_parts") or []
    if path_parts:
        return str(path_parts[0]).lower()
    return str(item.get("primary_category") or "other").lower()


def _item_text(item: dict[str, Any]) -> str:
    chunks = [
        item.get("item_id") or "",
        item.get("display_name") or "",
        item.get("type_name") or "",
        " ".join(str(v) for v in item.get("path_parts", [])),
        " ".join(str(v) for v in item.get("semantic_tags", [])),
        " ".join(str(v) for v in item.get("variant_tokens", [])),
        " ".join(str(v) for v in item.get("recolor_tokens", [])),
        item.get("search_text") or "",
    ]
    return " ".join(str(chunk) for chunk in chunks if chunk)


def _normalize_vector(counter: Counter[str], idf_map: dict[str, float]) -> dict[str, float]:
    weighted: dict[str, float] = {}
    for token, tf in counter.items():
        idf = idf_map.get(token)
        if idf is None:
            continue
        weighted[token] = float(tf) * idf

    norm = math.sqrt(sum(value * value for value in weighted.values()))
    if norm <= 0:
        return {}
    return {token: value / norm for token, value in weighted.items()}


def build_vector_index(scan_result: dict[str, Any]) -> dict[str, Any]:
    items_by_id: dict[str, dict[str, Any]] = scan_result.get("items_by_id", {})
    token_counters: dict[str, Counter[str]] = {}
    doc_freq: Counter[str] = Counter()

    for item_id, item in items_by_id.items():
        counter = Counter(_tokenize(_item_text(item)))
        token_counters[item_id] = counter
        doc_freq.update(counter.keys())

    doc_count = max(1, len(token_counters))
    idf_map = {
        token: math.log((doc_count + 1) / (freq + 1)) + 1.0
        for token, freq in doc_freq.items()
    }

    categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item_id, item in items_by_id.items():
        vector = _normalize_vector(token_counters[item_id], idf_map)
        categories[_source_category(item)].append(
            {
                "item_id": item_id,
                "display_name": item.get("display_name") or item_id,
                "type_name": item.get("type_name"),
                "primary_category": item.get("primary_category"),
                "source_category": _source_category(item),
                "semantic_tags": item.get("semantic_tags", []),
                "supports_body_types": item.get("supports_body_types", []),
                "is_custom": _is_custom_item(item),
                "layer_count": int(item.get("layer_count", 0) or 0),
                "vector": {token: round(weight, 8) for token, weight in vector.items()},
            }
        )

    for source_category in list(categories.keys()):
        categories[source_category].sort(key=lambda item: item["item_id"])

    return {
        "version": 1,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "doc_count": doc_count,
        "idf": {token: round(value, 8) for token, value in idf_map.items()},
        "categories": dict(categories),
    }


def write_vector_index(
    output_path: Path | str = DEFAULT_VECTOR_INDEX_PATH,
    scan_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if scan_result is None:
        raise ValueError("scan_result is required to build vector index.")
    output_path = Path(output_path)
    payload = build_vector_index(scan_result)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def load_vector_index(path: Path | str = DEFAULT_VECTOR_INDEX_PATH) -> dict[str, Any]:
    index_path = Path(path)
    if not index_path.exists():
        return {}
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _query_vector(query_text: str, idf_map: dict[str, float]) -> dict[str, float]:
    counter = Counter(_tokenize(query_text))
    return _normalize_vector(counter, idf_map)


def _dot(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(float(value) * float(right.get(token, 0.0)) for token, value in left.items())


def search_by_source_category(
    *,
    index_payload: dict[str, Any],
    query_text: str,
    source_category: str,
    top_k: int = 40,
    include_custom: bool = True,
) -> list[dict[str, Any]]:
    categories = index_payload.get("categories")
    if not isinstance(categories, dict):
        return []

    bucket = categories.get(str(source_category).lower(), [])
    if not isinstance(bucket, list) or not bucket:
        return []

    idf_map = index_payload.get("idf", {})
    if not isinstance(idf_map, dict):
        return []

    query_vec = _query_vector(query_text, {str(k): float(v) for k, v in idf_map.items()})
    if not query_vec:
        return []

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for item in bucket:
        if not include_custom and bool(item.get("is_custom")):
            continue
        vector = item.get("vector", {})
        if not isinstance(vector, dict):
            continue
        score = _dot(query_vec, {str(k): float(v) for k, v in vector.items()})
        if score <= 0:
            continue
        scored.append((score, int(item.get("layer_count", 0) or 0), item))

    scored.sort(key=lambda row: (row[0], row[1], row[2].get("item_id", "")), reverse=True)
    top = scored[: max(1, int(top_k))]
    return [
        {
            "item_id": row[2].get("item_id"),
            "display_name": row[2].get("display_name"),
            "type_name": row[2].get("type_name"),
            "source_category": row[2].get("source_category"),
            "primary_category": row[2].get("primary_category"),
            "semantic_tags": row[2].get("semantic_tags", []),
            "supports_body_types": row[2].get("supports_body_types", []),
            "is_custom": bool(row[2].get("is_custom")),
            "score": round(float(row[0]), 8),
        }
        for row in top
    ]
