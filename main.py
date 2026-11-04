import base64
import io
import json
import re
import shutil
import ssl
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib import error, request

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

import lpc_vector_index
import scanner
from relay_config import load_relay_config

try:
    from rembg import remove as rembg_remove
except Exception:  # noqa: BLE001
    rembg_remove = None

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent
GENERATOR_DIR = ROOT_DIR / "generator"
FRONTEND_LAB_DIR = ROOT_DIR / "frontend_lab"
MANIFEST_PATH = ROOT_DIR / "manifest.json"
ASSET_CATALOG_PATH = ROOT_DIR / "asset_catalog.json"
VECTOR_INDEX_PATH = ROOT_DIR / "lpc_vector_index.json"
BACKUP_ROOT = ROOT_DIR / "backups"
BODY_TYPE_KEYS = ("male", "female", "teen", "child", "muscular", "pregnant")
ANIMATION_FOLDER_ALIASES = {
    "combat": "combat_idle",
    "1h_slash": "backslash",
    "1h_backslash": "backslash",
    "1h_halfslash": "halfslash",
}
DEFAULT_LAYER_FALLBACKS = {
    "body": "body",
    "hair": "hair_single",
    "armor": "torso_armour_plate",
    "weapons": "weapon_sword_longsword",
}
SLOT_TO_MANIFEST_CATEGORIES = {
    "body": ("body",),
    "hair": ("hair",),
    "armor": ("torso", "armor", "armour"),
    "weapons": ("weapons", "weapon"),
    "torso": ("torso", "armor", "armour"),
    "legs": ("legs",),
    "feet": ("feet", "shoe", "shoes", "boot", "boots", "sandals", "slippers"),
    "hat": ("hat", "headwear", "helmet"),
    "head": ("head",),
    "expression": ("expression",),
    "cape": ("cape",),
    "shield": ("shield", "weapons", "weapon"),
}
SLOT_TO_SOURCE_CATEGORIES = {
    "body": ("body",),
    "hair": ("hair",),
    "armor": ("torso",),
    "weapons": ("weapons",),
    "torso": ("torso",),
    "legs": ("legs",),
    "feet": ("feet",),
    "hat": ("hat",),
    "head": ("head",),
    "expression": ("expression",),
    "cape": ("cape",),
    "shield": ("weapons",),
}
TOKEN_SYNONYM_MAP = {
    "步枪": "rifle firearm gun",
    "火枪": "rifle firearm musket gun",
    "长枪": "spear polearm",
    "大刀": "broadsword greatsword longsword blade sword",
    "阔剑": "broadsword greatsword longsword sword",
    "海军裙": "navy sailor skirt dress uniform",
    "武士刀": "katana sword blade",
    "太刀": "katana sword blade",
    "t恤": "tshirt shirt tee top",
    "t-shirt": "tshirt shirt tee top",
    "tee": "tshirt shirt tee top",
    "白人": "white light skin",
    "白皙": "white light skin",
    "帆布鞋": "canvas shoe sneaker",
    "年轻女性": "young female woman girl",
    "双截棍": "nunchuck flail",
    "十字弩": "crossbow",
    "弩": "crossbow",
    "弓": "bow",
    "长剑": "longsword sword",
    "寒冰": "ice frost",
    "冰蓝": "ice blue cyan",
    "轻甲": "light armor leather",
    "重甲": "heavy armor plate",
    "鸭舌帽": "cap hat",
    "头盔": "helmet hat",
    "短发": "short hair",
    "长发": "long hair",
    "红色": "red",
    "黑色": "black",
    "粉色": "pink",
}
COLOR_FAMILIES: dict[str, dict[str, list[str]]] = {
    "pink": {
        "aliases": ["粉", "粉色", "pink", "rose", "fuchsia", "magenta"],
        "tokens": ["pink", "rose", "lavender", "purple", "magenta"],
    },
    "ice_blue": {
        "aliases": ["寒冰", "冰蓝", "冰霜", "霜蓝", "冰", "ice", "icy", "frost", "glacier"],
        "tokens": ["ice", "iceblue", "whitecyan", "sky", "cyan", "blue", "teal", "navy"],
    },
    "black": {
        "aliases": ["黑", "黑色", "black", "dark", "shadow"],
        "tokens": ["black", "charcoal", "darkgray", "gray"],
    },
    "red": {
        "aliases": ["红", "红色", "赤", "red", "crimson", "scarlet", "ruby"],
        "tokens": ["red", "darkred", "ruby", "maroon", "scarlet"],
    },
    "blue": {
        "aliases": ["蓝", "蓝色", "blue", "azure", "cyan"],
        "tokens": ["blue", "sky", "teal", "navy", "cyan"],
    },
    "green": {
        "aliases": ["绿", "绿色", "green", "emerald", "forest"],
        "tokens": ["green", "forest", "olive", "teal"],
    },
    "purple": {
        "aliases": ["紫", "紫色", "purple", "violet", "lavender"],
        "tokens": ["purple", "violet", "lavender", "rose"],
    },
    "gold": {
        "aliases": ["金", "金色", "黄", "黄色", "gold", "yellow", "amber"],
        "tokens": ["gold", "yellow", "amber", "orange", "tan"],
    },
    "white": {
        "aliases": ["白", "白色", "银", "银色", "white", "silver", "platinum"],
        "tokens": ["white", "silver", "platinum", "gray", "light"],
    },
    "brown": {
        "aliases": ["棕", "棕色", "褐", "brown", "tan", "leather"],
        "tokens": ["brown", "light", "dark", "chestnut", "walnut", "tan", "leather"],
    },
    "navy": {
        "aliases": ["海军", "海军蓝", "navy", "marine"],
        "tokens": ["navy", "blue", "teal"],
    },
}
SLOT_KEYWORDS: dict[str, list[str]] = {
    "hair": ["头发", "发色", "短发", "长发", "hair", "hairstyle", "ponytail"],
    "armor": ["轻甲", "重甲", "护甲", "盔甲", "armor", "armour", "mail", "plate", "leather", "裙", "dress", "skirt", "制服"],
    "hat": ["帽", "帽子", "鸭舌帽", "头盔", "hat", "cap", "helmet", "hood"],
    "weapons": ["剑", "武器", "刀", "枪", "斧", "锤", "双截棍", "weapon", "sword", "axe", "spear", "staff", "flail", "rifle", "gun"],
    "body": ["肤色", "皮肤", "skin", "skintone", "女性", "男性", "woman", "female", "male"],
    "feet": ["鞋", "靴", "帆布鞋", "shoe", "sneaker", "boot", "sandal", "slipper"],
    "legs": ["裤", "裙", "短裤", "长裤", "pants", "shorts", "skirt", "leggings"],
    "torso": ["上衣", "外套", "夹克", "裙", "连衣裙", "shirt", "jacket", "dress", "uniform", "sailor"],
}
PROMPT_EXTENDED_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "feet": SLOT_KEYWORDS["feet"],
    "legs": SLOT_KEYWORDS["legs"],
    "hat": SLOT_KEYWORDS["hat"],
    "cape": ["披风", "斗篷", "cape", "cloak"],
    "shield": ["盾", "盾牌", "shield", "buckler"],
    "head": ["脸", "head", "face", "面部"],
    "expression": ["表情", "expression", "smile", "angry", "cry"],
}

ANALYZE_SYSTEM_PROMPT_TEMPLATE = """# Role
You are the "LPC Asset Logic Orchestrator," a high-precision engine designed to map natural language character descriptions to the "Liberated Pixel Cup" (LPC) asset framework.

# Context
The LPC framework uses a layered 2D spritesheet system. Assets must be selected in a specific stack order: [Body -> Hair -> Armor -> Weapons]. Your goal is to maximize the use of existing assets while identifying gaps that require AI generation.

# Knowledge Base: Local Manifest
The following JSON represents the currently available assets in the local directory:
{{manifest_json}}

# Decision Logic & Constraints
1. **Direct Mapping**: Analyze the user's description. Map keywords to the closest available asset in the manifest (e.g., "Warrior" -> "Armor: plate_silver").
2. **Missing Asset Identification**: If the user requests an item that has no semantic match in the manifest (e.g., "Nunchucks" but 'weapons' only contains 'sword'), you MUST flag it for generation.
3. **Style Consistency**: All missing assets must be generated in a specific style to ensure they can be pixelated and aligned later.
4. **Color Logic**: If a user specifies a color not in the manifest, prioritize selecting the "Base" version (if exists) or flag it for generation if it's a unique item.

# Output Format (Strict JSON)
Your response must be a valid JSON object with NO additional text.
{
  "character_summary": "A brief technical summary of the character concept.",
  "selected_layers": {
    "body": "string | null",
    "hair": "string | null",
    "armor": "string | null",
    "weapons": "string | null"
  },
  "extended_layers": {
    "hat": "string | null",
    "head": "string | null",
    "expression": "string | null",
    "cape": "string | null",
    "shield": "string | null"
  },
  "generation_tasks": [
    {
      "category": "string (e.g., weapons)",
      "internal_name": "string (e.g., nunchuck_wooden)",
      "gen_prompt": "A professional-grade game asset prompt for this item. Requirements: High-quality 2D digital art, isolated on a solid #00FF00 green background, front-facing orthographic view, sharp edges, no shadows, vibrant colors.",
      "visual_prompt": "Detailed visual prompt for downstream image generation.",
      "design_notes": "Optional implementation note for sprite alignment/layering."
    }
  ],
  "is_complete": true
}

# Prompt Engineering for Generation Tasks
When creating `gen_prompt`, always include:
"Isolated on #00FF00 green screen, 2D game icon style, high contrast, clean silhouette, orthographic perspective."
This ensures the `rembg` tool and pixelation script can process it.

# Compatibility Requirement
Always include `visual_prompt` in each generation task and keep `design_notes` when helpful.

# Coverage Requirement
In addition to the 4 core layers, detect explicit user-mentioned accessories/features
(e.g., hat/headwear, head/expression, shield, cape, backpack, beard/mustache).
Put them in `extended_layers` using valid existing item_ids whenever available.
"""
LPC_ONLY_PROMPT_APPENDIX = """

# Runtime Mode
GEN mode is OFF. You are in LPC-only compatibility mode.

# Additional hard constraints (highest priority)
1. You MUST NOT invent or request any new asset IDs.
2. You MUST NOT return generation tasks.
3. For each layer [body, hair, armor, weapons], choose the closest existing item_id from manifest.
4. Mapping priority: Category > Material > Color.
5. Output is still strict JSON with valid selected_layers IDs from manifest.
6. If user explicitly mentions extra items (hat/cape/shield/expression etc.), include them in `extended_layers` too.
7. Do not choose undead/special forms (e.g., zombie/skeleton) unless explicitly requested.
"""

app = FastAPI(title="Sprite Toolkit AI Backend", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
if GENERATOR_DIR.exists():
    app.mount("/generator", StaticFiles(directory=GENERATOR_DIR, html=True), name="generator")
else:
    @app.get("/generator/{asset_path:path}")
    def generator_assets_unavailable(asset_path: str) -> None:
        raise HTTPException(
            status_code=503,
            detail="Install LPC assets with scripts/setup_lpc_generator.sh to enable generator previews.",
        )

app.mount("/frontend_lab", StaticFiles(directory=FRONTEND_LAB_DIR, html=True), name="frontend_lab")


class TextRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="User prompt for AI text logic.")


class TextResponse(BaseModel):
    output: str


class RemoveBgRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 image payload without data URL prefix.")


class RemoveBgResponse(BaseModel):
    image_base64: str


class SelectedLayers(BaseModel):
    body: str | None = None
    hair: str | None = None
    armor: str | None = None
    weapons: str | None = None


class GenerationTask(BaseModel):
    category: str
    internal_name: str
    gen_prompt: str
    visual_prompt: str | None = None
    design_notes: str | None = None


class AnalyzeLLMOutput(BaseModel):
    character_summary: str
    selected_layers: SelectedLayers
    extended_layers: dict[str, str | None] = Field(default_factory=dict)
    generation_tasks: list[GenerationTask] = Field(default_factory=list)
    is_complete: bool


class MissingAsset(BaseModel):
    category: str
    internal_name: str
    visual_prompt: str
    design_notes: str | None = None


class AnalyzeRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    gen_mode: bool | None = None


class AnalyzeResponse(BaseModel):
    mode_resolved: Literal["GEN", "LPC_ONLY"]
    character_summary: str
    selected_layers: SelectedLayers
    extended_layers: dict[str, str | None] = Field(default_factory=dict)
    generation_tasks: list[GenerationTask]
    missing_assets: list[MissingAsset]
    is_complete: bool
    manifest_refreshed_at: str
    warnings_count: int


class RegisterGeneratedAssetRequest(BaseModel):
    category: Literal["body", "hair", "armor", "weapons"]
    internal_name: str = Field(..., min_length=1)
    display_name: str | None = None
    spritesheet_root: str = Field(..., min_length=1)
    template_item_id: str | None = None
    gen_mode: bool | None = None
    image_base64: str | None = Field(
        default=None,
        description="Optional single-image payload. When set, backend normalizes and expands it into LPC spritesheets.",
    )


class PrecheckResult(BaseModel):
    png_count: int
    animation_hint_matched: bool


class RegisterGeneratedAssetResponse(BaseModel):
    definition_file: str
    template_used: str
    selection_reason: str
    precheck: PrecheckResult
    single_image_processed: bool = False
    generated_png_files: int = 0
    metadata_rebuilt: bool
    backup_files: list[str]
    manifest_updated: bool


class AssetLookupResponse(BaseModel):
    item_id: str
    category: str
    is_custom: bool
    definition_file: str
    display_name: str
    type_name: str | None = None


class ExecuteRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    gen_mode: bool | None = None
    max_generation_tasks: int | None = Field(default=None, ge=1)
    auto_register: bool = True


class GeneratedAssetResult(BaseModel):
    category: str
    internal_name: str
    image_status: Literal["succeeded", "failed", "skipped"]
    register_status: Literal["succeeded", "failed", "skipped"]
    image_error: str | None = None
    register_error: str | None = None
    definition_file: str | None = None


class ExecuteResponse(BaseModel):
    mode_resolved: Literal["GEN", "LPC_ONLY"]
    overall_status: Literal["success", "partial_success", "failed"]
    analysis_before: AnalyzeResponse
    generated_assets: list[GeneratedAssetResult]
    analysis_after: AnalyzeResponse | None = None
    errors: list[str] = Field(default_factory=list)


def _tokenize(text: str) -> list[str]:
    normalized = str(text or "").lower()
    for phrase, expansion in sorted(TOKEN_SYNONYM_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if phrase in normalized:
            normalized = normalized.replace(phrase, f" {phrase} {expansion} ")

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


def _normalize_internal_name(name: str) -> str:
    normalized = "_".join(_tokenize(name))
    if not normalized:
        raise ValueError("internal_name must contain at least one alphanumeric token.")
    return normalized


def _to_title_case_from_internal_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("_"))


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = set(_tokenize(left))
    right_tokens = set(_tokenize(right))
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def build_missing_assets(generation_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing_assets: list[dict[str, Any]] = []
    for task in generation_tasks:
        visual_prompt = (task.get("visual_prompt") or task.get("gen_prompt") or "").strip()
        if not visual_prompt:
            continue

        missing_assets.append(
            {
                "category": str(task.get("category", "")).strip(),
                "internal_name": str(task.get("internal_name", "")).strip(),
                "visual_prompt": visual_prompt,
                "design_notes": (task.get("design_notes") or None),
            }
        )
    return missing_assets


def _infer_requested_body_type(prompt_text: str) -> str | None:
    lowered = str(prompt_text or "").lower()
    if not lowered:
        return None
    if re.search(r"child|kid|boy|girl|儿童|小孩|孩子", lowered):
        return "child"
    if re.search(r"pregnant|孕妇|怀孕", lowered):
        return "pregnant"
    if re.search(r"muscular|壮汉|肌肉", lowered):
        return "muscular"
    if re.search(r"female|woman|girl|女性|女生|女孩|少女", lowered):
        return "female"
    if re.search(r"male|man|boy|男性|男生|男孩", lowered):
        return "male"
    return None


def _item_supports_body_type(item: dict[str, Any], requested_body_type: str | None) -> bool:
    if not requested_body_type:
        return True
    supported = item.get("supports_body_types", [])
    if not isinstance(supported, list) or not supported:
        return True
    supported_set = {str(value).lower() for value in supported}
    return requested_body_type.lower() in supported_set


def _sanitize_json_text(raw_text: str) -> str:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def extract_text_from_gemini_response(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message = first_choice.get("message", {})
        content = message.get("content")

        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts).strip()

    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        first_candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first_candidate.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []

        texts = []
        for item in parts:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    texts.append(text)
        return "".join(texts).strip()

    return ""


def _build_ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _urlopen_with_ssl(req: request.Request, *, timeout: int):
    context = _build_ssl_context()
    return request.urlopen(req, timeout=timeout, context=context)


def _messages_to_generate_content_payload(
    messages: list[dict[str, str]],
    *,
    temperature: float,
    require_json_response: bool,
) -> dict[str, Any]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role", "")).strip().lower()
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        mapped_role = "model" if role == "assistant" else "user"
        contents.append({"role": mapped_role, "parts": [{"text": content}]})

    payload: dict[str, Any] = {
        "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
        "generationConfig": {
            "temperature": temperature,
        },
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    if require_json_response:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    return payload


def call_gemini_relay(
    messages: list[dict[str, str]],
    *,
    require_json_response: bool = False,
    temperature: float = 0.2,
) -> str:
    relay_config = load_relay_config()
    if not relay_config.llm.api_key:
        raise HTTPException(
            status_code=500,
            detail="LLM relay API key is not set. Configure service_config.json or env GEMINI_API_KEY/LLM_RELAY_API_KEY.",
        )
    if not relay_config.llm.url:
        raise HTTPException(
            status_code=500,
            detail="LLM relay URL is not set. Configure service_config.json or env GEMINI_RELAY_URL/LLM_RELAY_URL.",
        )

    url_text = relay_config.llm.url
    use_generate_content = "generatecontent" in url_text.lower()

    if use_generate_content:
        req_payload = _messages_to_generate_content_payload(
            messages,
            temperature=temperature,
            require_json_response=require_json_response,
        )
    else:
        req_payload = {
            "model": relay_config.llm.model,
            "messages": messages,
            "temperature": temperature,
        }
        if require_json_response:
            req_payload["response_format"] = {"type": "json_object"}

    req_data = json.dumps(req_payload).encode("utf-8")
    req = request.Request(
        url_text,
        data=req_data,
        headers={
            "Authorization": f"Bearer {relay_config.llm.api_key}",
            "x-goog-api-key": relay_config.llm.api_key,
            "Content-Type": "application/json",
            "User-Agent": "sprite-toolkit/1.0",
        },
        method="POST",
    )

    try:
        with _urlopen_with_ssl(req, timeout=90) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=502, detail=f"Gemini relay HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini relay network error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Gemini relay request failed: {exc}") from exc

    try:
        resp_payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from Gemini relay: {exc}") from exc

    output_text = extract_text_from_gemini_response(resp_payload)
    if not output_text:
        raise HTTPException(status_code=502, detail="Gemini relay returned empty output.")
    return output_text


def _to_base64_png_from_url(url_text: str) -> str:
    try:
        with _urlopen_with_ssl(request.Request(url_text, method="GET"), timeout=90) as response:
            image_bytes = response.read()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to download generated image from URL: {exc}") from exc
    return base64.b64encode(image_bytes).decode("utf-8")


def _extract_image_base64_from_payload(payload: dict[str, Any]) -> str | None:
    candidate_containers: list[Any] = [payload]
    for key in ("data", "images", "results", "output"):
        value = payload.get(key)
        if value is not None:
            candidate_containers.append(value)

    for container in candidate_containers:
        entries: list[Any]
        if isinstance(container, list):
            entries = container
        else:
            entries = [container]

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for key in ("b64_json", "b64", "image_base64", "base64"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            url_value = entry.get("url")
            if isinstance(url_value, str) and url_value.strip():
                return _to_base64_png_from_url(url_value.strip())
    return None


def call_image_relay(prompt: str, *, size: str = "1:1", n: int = 1) -> str:
    relay_config = load_relay_config()
    if not relay_config.image.api_key:
        raise ValueError("Image relay API key is not configured.")
    if not relay_config.image.url:
        raise ValueError("Image relay URL is not configured.")

    req_payload: dict[str, Any] = {
        "model": relay_config.image.model,
        "prompt": prompt,
        "size": size,
        "n": n,
    }

    req = request.Request(
        relay_config.image.url,
        data=json.dumps(req_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {relay_config.image.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "sprite-toolkit/1.0",
        },
        method="POST",
    )
    try:
        with _urlopen_with_ssl(req, timeout=120) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"Image relay HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise ValueError(f"Image relay network error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Image relay request failed: {exc}") from exc

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Image relay returned invalid JSON: {exc}") from exc

    image_base64 = _extract_image_base64_from_payload(payload)
    if not image_base64:
        raise ValueError("Image relay response did not contain image data.")
    return image_base64


def _refresh_manifest() -> tuple[dict[str, Any], str]:
    scan_result = scanner.write_manifest(
        output_path=MANIFEST_PATH,
        definitions_root=scanner.DEFAULT_DEFINITIONS_ROOT,
        sprites_root=scanner.DEFAULT_SPRITES_ROOT,
    )
    scanner.write_asset_catalog(output_path=ASSET_CATALOG_PATH, scan_result=scan_result)
    lpc_vector_index.write_vector_index(output_path=VECTOR_INDEX_PATH, scan_result=scan_result)
    manifest_json = MANIFEST_PATH.read_text(encoding="utf-8")
    return scan_result, manifest_json


def resolve_gen_mode(gen_mode_override: bool | None) -> bool:
    runtime = load_relay_config().runtime
    if gen_mode_override is None:
        return bool(runtime.gen_mode_default)
    return bool(gen_mode_override)


def _mode_label(gen_mode_enabled: bool) -> Literal["GEN", "LPC_ONLY"]:
    return "GEN" if gen_mode_enabled else "LPC_ONLY"


def _build_analyze_system_prompt(manifest_json: str, *, gen_mode_enabled: bool) -> str:
    prompt = ANALYZE_SYSTEM_PROMPT_TEMPLATE.replace("{{manifest_json}}", manifest_json)
    if not gen_mode_enabled:
        prompt += LPC_ONLY_PROMPT_APPENDIX
    return prompt


def _slot_manifest_categories(slot: str) -> tuple[str, ...]:
    key = str(slot or "").strip().lower()
    return SLOT_TO_MANIFEST_CATEGORIES.get(key, (key,))


def _slot_source_categories(slot: str) -> tuple[str, ...]:
    key = str(slot or "").strip().lower()
    return SLOT_TO_SOURCE_CATEGORIES.get(key, (key,))


def _load_vector_index_or_build(scan_result: dict[str, Any]) -> dict[str, Any]:
    payload = lpc_vector_index.load_vector_index(VECTOR_INDEX_PATH)
    if payload:
        return payload
    return lpc_vector_index.write_vector_index(output_path=VECTOR_INDEX_PATH, scan_result=scan_result)


def _collect_vector_candidates_for_slot(
    *,
    index_payload: dict[str, Any],
    prompt_text: str,
    slot: str,
    include_custom: bool,
    requested_body_type: str | None,
    top_k: int = 48,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source_category in _slot_source_categories(slot):
        items = lpc_vector_index.search_by_source_category(
            index_payload=index_payload,
            query_text=prompt_text,
            source_category=source_category,
            top_k=top_k,
            include_custom=include_custom,
        )
        for candidate in items:
            item_id = str(candidate.get("item_id", "")).strip()
            if not item_id:
                continue
            support_types = candidate.get("supports_body_types", [])
            if requested_body_type and isinstance(support_types, list) and support_types:
                if requested_body_type.lower() not in {str(value).lower() for value in support_types}:
                    continue
            existing = merged.get(item_id)
            if not existing or float(candidate.get("score", 0.0)) > float(existing.get("score", 0.0)):
                merged[item_id] = candidate

    return sorted(
        merged.values(),
        key=lambda item: (float(item.get("score", 0.0)), str(item.get("item_id", ""))),
        reverse=True,
    )[:top_k]


def _build_manifest_context_for_prompt(
    scan_result: dict[str, Any],
    *,
    prompt_text: str,
    include_custom: bool,
) -> str:
    index_payload = _load_vector_index_or_build(scan_result)
    summary = scan_result.get("summary", {})
    requested_body_type = _infer_requested_body_type(prompt_text)

    slots = ["body", "hair", "armor", "weapons"]
    slots.extend(category for category in _infer_prompt_extended_categories(prompt_text) if category not in slots)

    context_payload: dict[str, Any] = {
        "strict_lpc_category_mode": True,
        "slot_to_source_categories": {slot: list(_slot_source_categories(slot)) for slot in slots},
        "slot_candidates": {},
        "catalog_summary": {
            "total_items": summary.get("total_items", 0),
            "top_folders": summary.get("top_folders", []),
        },
        "requested_body_type": requested_body_type,
    }

    for slot in slots:
        candidates = _collect_vector_candidates_for_slot(
            index_payload=index_payload,
            prompt_text=prompt_text,
            slot=slot,
            include_custom=include_custom,
            requested_body_type=requested_body_type,
        )
        context_payload["slot_candidates"][slot] = [
            {
                "item_id": candidate.get("item_id"),
                "display_name": candidate.get("display_name"),
                "type_name": candidate.get("type_name"),
                "source_category": candidate.get("source_category"),
                "primary_category": candidate.get("primary_category"),
                "semantic_tags": candidate.get("semantic_tags", [])[:14],
                "score": candidate.get("score", 0.0),
            }
            for candidate in candidates
        ]

    return json.dumps(context_payload, ensure_ascii=False)


def _is_custom_item_record(item: dict[str, Any]) -> bool:
    path_parts = [str(part).lower() for part in item.get("path_parts", [])]
    definition_file = str(item.get("definition_file", "")).replace("\\", "/").lower()
    return "custom" in path_parts or "/custom/" in definition_file


def _validate_selected_layers(selected_layers: SelectedLayers, manifest: dict[str, list[str]]) -> SelectedLayers:
    allowed: dict[str, set[str]] = {}
    for layer_key in ("body", "hair", "armor", "weapons"):
        category_aliases = _slot_manifest_categories(layer_key)
        bucket: set[str] = set()
        for category in category_aliases:
            bucket.update(manifest.get(category, []))
        allowed[layer_key] = bucket
    return SelectedLayers(
        body=selected_layers.body if selected_layers.body in allowed["body"] else None,
        hair=selected_layers.hair if selected_layers.hair in allowed["hair"] else None,
        armor=selected_layers.armor if selected_layers.armor in allowed["armor"] else None,
        weapons=selected_layers.weapons if selected_layers.weapons in allowed["weapons"] else None,
    )


def _dedupe_overlapping_layers(
    selected_layers: SelectedLayers,
    extended_layers: dict[str, str],
) -> dict[str, str]:
    cleaned = dict(extended_layers)
    if cleaned.get("torso") and selected_layers.armor and cleaned.get("torso") == selected_layers.armor:
        cleaned.pop("torso", None)
    return cleaned


def _filter_incompatible_layers_by_body_type(
    *,
    selected_layers: SelectedLayers,
    extended_layers: dict[str, str],
    scan_result: dict[str, Any],
    requested_body_type: str | None,
) -> tuple[SelectedLayers, dict[str, str]]:
    if not requested_body_type:
        return selected_layers, extended_layers

    items_by_id: dict[str, dict[str, Any]] = scan_result.get("items_by_id", {})

    def _compatible(item_id: str | None) -> str | None:
        if not item_id:
            return None
        item = items_by_id.get(item_id)
        if not item:
            return None
        return item_id if _item_supports_body_type(item, requested_body_type) else None

    cleaned_selected = SelectedLayers(
        body=_compatible(selected_layers.body),
        hair=_compatible(selected_layers.hair),
        armor=_compatible(selected_layers.armor),
        weapons=_compatible(selected_layers.weapons),
    )

    cleaned_extended: dict[str, str] = {}
    for key, value in extended_layers.items():
        item = items_by_id.get(value)
        if not item:
            continue
        if _item_supports_body_type(item, requested_body_type):
            cleaned_extended[key] = value

    return cleaned_selected, cleaned_extended


def _validate_extended_layers(
    extended_layers: dict[str, str | None],
    items_by_id: dict[str, dict[str, Any]],
) -> dict[str, str]:
    validated: dict[str, str] = {}
    for key, value in (extended_layers or {}).items():
        if value is None:
            continue
        category_key = "_".join(_tokenize(str(key)))
        item_id = str(value).strip()
        if not category_key or not item_id:
            continue
        if category_key == "torso":
            continue
        if item_id not in items_by_id:
            continue
        validated[category_key] = item_id
    return validated


def _pick_color_family_in_segment(segment: str) -> str | None:
    lowered = str(segment or "").lower()
    if not lowered:
        return None

    best_family: str | None = None
    best_index: int | None = None
    for family, cfg in COLOR_FAMILIES.items():
        for alias in cfg.get("aliases", []):
            idx = lowered.find(str(alias).lower())
            if idx < 0:
                continue
            if best_index is None or idx < best_index:
                best_family = family
                best_index = idx
    return best_family


def _extract_color_intent(prompt_text: str) -> dict[str, str]:
    prompt = str(prompt_text or "").strip()
    if not prompt:
        return {}

    intent: dict[str, str] = {}
    segments = [seg.strip() for seg in re.split(r"[，,。；;！!？?\n]+", prompt) if seg.strip()]
    for segment in segments:
        family = _pick_color_family_in_segment(segment)
        if not family:
            continue
        lowered = segment.lower()
        matched_slots = [
            slot
            for slot, keywords in SLOT_KEYWORDS.items()
            if any(str(keyword).lower() in lowered for keyword in keywords)
        ]
        if matched_slots:
            for slot in matched_slots:
                intent.setdefault(slot, family)
        else:
            intent.setdefault("global", family)

    lowered_prompt = prompt.lower()
    if re.search(r"海军裙|sailor", lowered_prompt):
        intent.setdefault("armor", "navy")
    if re.search(r"帆布鞋|canvas|sneaker", lowered_prompt):
        if "红" in lowered_prompt or "red" in lowered_prompt:
            intent.setdefault("feet", "red")
    if re.search(r"金色.{0,6}(头发|短发|长发|发色)|(?:头发|短发|长发|发色).{0,6}金色|gold.{0,6}hair|hair.{0,6}gold", lowered_prompt):
        intent.setdefault("hair", "gold")
    return intent


def _resolve_color_slot(category: str, type_name: str | None) -> str:
    normalized_category = str(category or "").lower()
    normalized_type = str(type_name or "").lower()
    if normalized_category in {"hair"} or normalized_type in {"hair", "beard", "mustache"}:
        return "hair"
    if normalized_category in {"armor", "torso"} or normalized_type in {"armour", "armor", "clothes", "dress", "jacket"}:
        return "armor"
    if normalized_category == "legs" or normalized_type in {"legs", "pants", "skirt"}:
        return "legs"
    if normalized_category == "feet" or normalized_type in {"feet", "shoe", "boots", "slippers", "sandals"}:
        return "feet"
    if normalized_category in {"weapons", "weapon"} or normalized_type in {"weapon", "shield"}:
        return "weapons"
    if normalized_category in {"hat", "headwear"} or "hat" in normalized_type or normalized_type == "helmet":
        return "hat"
    if normalized_category in {"body", "head", "expression"} or normalized_type in {"body", "head", "expression"}:
        return "body"
    return normalized_category or normalized_type or "global"


def _build_prompt_semantic_profile(prompt_text: str) -> dict[str, Any]:
    prompt_tokens = set(_tokenize(prompt_text))
    lowered = str(prompt_text or "").lower()

    weapon_prefer_tags: set[str] = set()
    weapon_avoid_tags: set[str] = set()
    weapon_prefer_tokens: set[str] = set()
    weapon_avoid_tokens: set[str] = set()
    armor_style_tokens: set[str] = set()
    feet_style_tokens: set[str] = set()
    legs_style_tokens: set[str] = set()
    hair_prefer_tokens: set[str] = set()
    hair_avoid_tokens: set[str] = set()

    if {"rifle", "firearm", "gun", "musket"} & prompt_tokens:
        weapon_prefer_tags.update({"weapon.firearm", "weapon.ranged"})
        weapon_prefer_tokens.update({"rifle", "firearm", "gun", "musket"})
        weapon_avoid_tags.update({"weapon.crossbow", "weapon.bow"})
        weapon_avoid_tokens.update({"crossbow", "bow"})

    if {"nunchuck", "flail"} & prompt_tokens:
        weapon_prefer_tokens.update({"nunchuck", "flail", "chain"})
        weapon_prefer_tags.update({"weapon.melee"})
        weapon_avoid_tags.update({"weapon.ranged"})

    if {"sword", "longsword", "blade", "broadsword", "greatsword", "katana", "saber", "scimitar"} & prompt_tokens or ("大刀" in lowered):
        weapon_prefer_tags.update({"weapon.sword", "weapon.melee"})
        weapon_prefer_tokens.update({"sword", "blade", "broadsword", "greatsword", "longsword", "katana", "saber", "scimitar"})
        weapon_avoid_tags.update({"weapon.crossbow", "weapon.bow"})
        weapon_avoid_tokens.update({"crossbow", "bow"})

    if {"crossbow"} & prompt_tokens:
        weapon_prefer_tags.update({"weapon.crossbow", "weapon.ranged"})
        weapon_prefer_tokens.update({"crossbow"})
    elif {"bow"} & prompt_tokens:
        weapon_prefer_tags.update({"weapon.bow", "weapon.ranged"})
        weapon_prefer_tokens.update({"bow"})

    if {"dress", "skirt", "kimono", "uniform", "sailor", "shirt", "tshirt", "tee", "blouse", "jacket"} & prompt_tokens or re.search(
        r"海军裙|连衣裙|短裙|长裙|上衣|t恤|衬衫|夹克", lowered
    ):
        armor_style_tokens.update(
            token
            for token in {"dress", "skirt", "kimono", "uniform", "sailor", "shirt", "tshirt", "tee", "blouse", "jacket"}
            if token in prompt_tokens
        )
        if re.search(r"t恤|t-shirt|tee|上衣", lowered):
            armor_style_tokens.update({"shirt", "tshirt", "tee"})
        if re.search(r"海军裙|连衣裙|短裙|长裙", lowered):
            armor_style_tokens.update({"dress", "skirt"})
        if not armor_style_tokens:
            armor_style_tokens.update({"shirt", "dress"})
        legs_style_tokens.update({"skirt", "leggings", "pants"})

    if {"shoe", "shoes", "sneaker", "boot", "boots", "sandal", "slipper", "canvas"} & prompt_tokens or re.search(
        r"鞋|靴|帆布鞋", lowered
    ):
        feet_style_tokens.update(
            token
            for token in {"shoe", "shoes", "sneaker", "boot", "boots", "sandal", "slipper", "canvas"}
            if token in prompt_tokens
        )
        if re.search(r"帆布鞋|canvas", lowered):
            feet_style_tokens.update({"canvas", "shoe", "shoes", "sneaker"})
        elif re.search(r"鞋", lowered):
            feet_style_tokens.update({"shoe", "shoes"})
        elif re.search(r"靴", lowered):
            feet_style_tokens.update({"boot", "boots"})
        if not feet_style_tokens:
            feet_style_tokens.update({"shoe", "shoes"})

    wants_female = bool(re.search(r"女性|女孩|少女|woman|female|girl", lowered))
    wants_male = bool(re.search(r"男性|男孩|man|male|boy", lowered))
    wants_undead = bool(re.search(r"zombie|skeleton|undead|僵尸|骷髅|亡灵", lowered))
    wants_short_hair = bool(re.search(r"短发|short hair|buzz|crew cut|寸头|平头", lowered))
    requested_body_type = _infer_requested_body_type(prompt_text)
    hair_require_long = bool({"long", "xlong"} & prompt_tokens or re.search(r"长发|long hair", lowered))
    if hair_require_long:
        hair_prefer_tokens.update({"long", "xlong", "longhair"})
        hair_avoid_tokens.update({"child", "short", "buzz", "bald", "mohawk"})
    if {"blonde", "blond", "gold"} & prompt_tokens or re.search(r"金发|金色头发|blond|blonde", lowered):
        hair_prefer_tokens.update({"blonde", "blond", "gold", "yellow", "platinum"})
    weapon_require_sword = bool(
        {"longsword", "broadsword", "greatsword", "katana", "saber", "scimitar", "sword", "blade"} & prompt_tokens
        or "大刀" in lowered
    )
    weapon_require_katana = bool({"katana", "samurai"} & prompt_tokens or re.search(r"武士刀|太刀", lowered))

    return {
        "prompt_tokens": prompt_tokens,
        "color_intent": _extract_color_intent(prompt_text),
        "weapon_prefer_tags": weapon_prefer_tags,
        "weapon_avoid_tags": weapon_avoid_tags,
        "weapon_prefer_tokens": weapon_prefer_tokens,
        "weapon_avoid_tokens": weapon_avoid_tokens,
        "armor_style_tokens": armor_style_tokens,
        "legs_style_tokens": legs_style_tokens,
        "feet_style_tokens": feet_style_tokens,
        "hair_prefer_tokens": hair_prefer_tokens,
        "hair_avoid_tokens": hair_avoid_tokens,
        "wants_female": wants_female,
        "wants_male": wants_male,
        "wants_undead": wants_undead,
        "wants_short_hair": wants_short_hair,
        "requested_body_type": requested_body_type,
        "hair_require_long": hair_require_long,
        "weapon_require_sword": weapon_require_sword,
        "weapon_require_katana": weapon_require_katana,
    }


def _candidate_token_set(candidate: dict[str, Any]) -> set[str]:
    chunks = [
        candidate.get("search_text") or "",
        candidate.get("item_id") or "",
        candidate.get("display_name") or "",
        candidate.get("type_name") or "",
        " ".join(str(value) for value in candidate.get("semantic_tags", [])),
        " ".join(str(value) for value in candidate.get("variant_tokens", [])),
        " ".join(str(value) for value in candidate.get("recolor_tokens", [])),
        " ".join(str(value) for value in candidate.get("path_parts", [])),
    ]
    return set(_tokenize(" ".join(str(chunk) for chunk in chunks if chunk)))


def _candidate_semantic_score(
    *,
    category: str,
    candidate: dict[str, Any],
    profile: dict[str, Any],
) -> float:
    prompt_tokens: set[str] = profile["prompt_tokens"]
    candidate_tokens = _candidate_token_set(candidate)
    semantic_tags = {str(tag).lower() for tag in candidate.get("semantic_tags", [])}
    requested_body_type = profile.get("requested_body_type")
    if isinstance(requested_body_type, str) and requested_body_type:
        if _item_supports_body_type(candidate, requested_body_type):
            score_body_bias = 0.22
        else:
            score_body_bias = -1.15
    else:
        score_body_bias = 0.0

    if prompt_tokens and candidate_tokens:
        lexical_jaccard = len(prompt_tokens & candidate_tokens) / len(prompt_tokens | candidate_tokens)
        lexical_overlap = len(prompt_tokens & candidate_tokens)
    else:
        lexical_jaccard = 0.0
        lexical_overlap = 0
    score = lexical_jaccard + (0.03 * lexical_overlap) + score_body_bias

    if not profile.get("wants_undead") and ({"zombie", "skeleton", "undead"} & candidate_tokens):
        score -= 2.2

    if category == "hair" and profile.get("wants_female") and not profile.get("wants_short_hair"):
        if {"long", "xlong", "wavy", "braid", "ponytail", "bob", "lob"} & candidate_tokens:
            score += 0.24
        if {"buzz", "bald", "mohawk", "high", "tight", "crewcut", "flat", "hawk", "balding"} & candidate_tokens:
            score -= 0.9

    if category == "feet" and {"canvas", "sneaker"} & profile.get("feet_style_tokens", set()):
        if "slipper" in candidate_tokens or "slippers" in candidate_tokens:
            score -= 0.95

    if category == "weapons":
        for tag in profile["weapon_prefer_tags"]:
            if tag in semantic_tags:
                score += 1.1
        for tag in profile["weapon_avoid_tags"]:
            if tag in semantic_tags:
                score -= 1.2
        for token in profile["weapon_prefer_tokens"]:
            if token in candidate_tokens:
                score += 0.4
        for token in profile["weapon_avoid_tokens"]:
            if token in candidate_tokens:
                score -= 0.5
        if profile.get("weapon_require_katana"):
            if {"katana", "samurai", "nodachi", "tachi"} & candidate_tokens:
                score += 1.0
            else:
                score -= 0.45

    if category == "armor":
        style_tokens = profile["armor_style_tokens"]
        if style_tokens:
            style_hit = len(style_tokens & candidate_tokens)
            if style_hit > 0:
                score += 0.65 + style_hit * 0.25
            elif str(candidate.get("primary_category") or "").lower() == "armor":
                score -= 0.3

    if category == "legs":
        style_tokens = profile["legs_style_tokens"]
        if style_tokens:
            style_hit = len(style_tokens & candidate_tokens)
            if style_hit > 0:
                score += 0.45 + style_hit * 0.2

    if category == "feet":
        style_tokens = profile["feet_style_tokens"]
        if style_tokens:
            style_hit = len(style_tokens & candidate_tokens)
            if style_hit > 0:
                score += 0.55 + style_hit * 0.2
            else:
                score -= 0.15
            if "outfit.footwear" in semantic_tags:
                score += 0.45
            else:
                score -= 0.3

    if category == "hair":
        for token in profile["hair_prefer_tokens"]:
            if token in candidate_tokens:
                score += 0.45
        for token in profile["hair_avoid_tokens"]:
            if token in candidate_tokens:
                score -= 0.35

    color_intent: dict[str, str] = profile["color_intent"]
    color_slot = _resolve_color_slot(category, candidate.get("type_name"))
    color_family = color_intent.get(color_slot) or color_intent.get("global")
    if color_family:
        desired_tokens = COLOR_FAMILIES.get(color_family, {}).get("tokens", [])
        desired_tags = {f"color.{token}".lower() for token in desired_tokens}
        if semantic_tags & desired_tags:
            score += 0.55
        elif desired_tags:
            score -= 0.08

    return score


def _local_similarity_select(
    *,
    prompt_text: str,
    candidates: list[dict[str, Any]],
) -> str | None:
    return _semantic_similarity_select(prompt_text=prompt_text, candidates=candidates)


def _semantic_similarity_select(
    *,
    prompt_text: str,
    candidates: list[dict[str, Any]],
    category: str | None = None,
) -> str | None:
    if not candidates:
        return None
    profile = _build_prompt_semantic_profile(prompt_text)

    scored: list[tuple[float, int, str]] = []
    normalized_category = str(category or "").lower()
    for candidate in candidates:
        item_id = str(candidate.get("item_id", "")).strip()
        if not item_id:
            continue
        candidate_category = normalized_category or str(candidate.get("primary_category") or "").lower()
        score = _candidate_semantic_score(
            category=candidate_category,
            candidate=candidate,
            profile=profile,
        )
        scored.append((score, int(candidate.get("layer_count", 0)), item_id))

    if not scored:
        return None
    scored.sort(reverse=True)
    best_score = scored[0][0]
    if best_score <= 0:
        return None
    return scored[0][2]


def _should_override_current_selection(
    *,
    category: str,
    current_item: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    tokens = _candidate_token_set(current_item)
    semantic_tags = {str(tag).lower() for tag in current_item.get("semantic_tags", [])}

    if category == "hair" and profile.get("hair_require_long"):
        has_long_hint = any(token in tokens for token in {"long", "xlong", "longs", "longhair"})
        if not has_long_hint:
            return True

    if category == "weapons" and profile.get("weapon_require_sword"):
        has_sword_hint = bool({"weapon.sword"} & semantic_tags) or any(
            token in tokens for token in {"sword", "longsword", "broadsword", "greatsword", "blade", "katana", "saber", "scimitar"}
        )
        if not has_sword_hint:
            return True
    if category == "weapons" and profile.get("weapon_require_katana"):
        if not any(token in tokens for token in {"katana", "samurai", "tachi", "nodachi"}):
            return True

    return False


def _apply_lpc_only_fallback(
    *,
    validated_layers: SelectedLayers,
    prompt_text: str,
    scan_result: dict[str, Any],
) -> SelectedLayers:
    runtime = load_relay_config().runtime
    use_non_custom_only = bool(runtime.lpc_only_exclude_custom)
    profile = _build_prompt_semantic_profile(prompt_text)
    requested_body_type = profile.get("requested_body_type")

    per_category_candidates: dict[str, list[dict[str, Any]]] = {
        category: _get_category_candidates(scan_result, category, include_custom=not use_non_custom_only)
        for category in ("body", "hair", "armor", "weapons")
    }
    if isinstance(requested_body_type, str) and requested_body_type:
        for category in ("body", "hair", "armor", "weapons"):
            filtered = [
                item for item in per_category_candidates[category] if _item_supports_body_type(item, requested_body_type)
            ]
            if filtered:
                per_category_candidates[category] = filtered
    items_by_id: dict[str, dict[str, Any]] = scan_result["items_by_id"]

    def _resolve_one(category: str, current_value: str | None) -> str | None:
        candidates = per_category_candidates[category]
        current_item: dict[str, Any] | None = None
        current_score: float | None = None
        if current_value:
            item = items_by_id.get(current_value)
            if item and (not use_non_custom_only or not _is_custom_item_record(item)):
                current_item = item
                current_score = _candidate_semantic_score(category=category, candidate=item, profile=profile)
            else:
                current_value = None

        matched = _semantic_similarity_select(
            prompt_text=prompt_text,
            candidates=candidates,
            category=category,
        )
        if matched:
            matched_item = items_by_id.get(matched)
            if not current_value or not current_item:
                return matched

            if _should_override_current_selection(category=category, current_item=current_item, profile=profile):
                return matched

            matched_score = _candidate_semantic_score(category=category, candidate=matched_item or {}, profile=profile)
            if current_score is None:
                return matched
            if matched_score >= current_score + 0.25:
                return matched
            return current_value

        if current_value and current_item:
            return current_value

        default_item = DEFAULT_LAYER_FALLBACKS.get(category)
        if default_item:
            default_record = items_by_id.get(default_item)
            if default_record and (not use_non_custom_only or not _is_custom_item_record(default_record)):
                return default_item

        if per_category_candidates[category]:
            return str(per_category_candidates[category][0]["item_id"])
        return current_value

    return SelectedLayers(
        body=_resolve_one("body", validated_layers.body),
        hair=_resolve_one("hair", validated_layers.hair),
        armor=_resolve_one("armor", validated_layers.armor),
        weapons=_resolve_one("weapons", validated_layers.weapons),
    )


def _category_preferred_type_names(category: str) -> set[str]:
    if category == "body":
        return {"body"}
    if category == "hair":
        return {"hair"}
    if category == "armor":
        return {"armour", "clothes", "dress", "jacket", "overalls", "apron", "chainmail"}
    if category == "weapons":
        return {"weapon", "shield", "ammo"}
    return set()


def _get_category_candidates(
    scan_result: dict[str, Any],
    category: str,
    *,
    include_custom: bool = True,
) -> list[dict[str, Any]]:
    items_by_id: dict[str, dict[str, Any]] = scan_result["items_by_id"]
    manifest: dict[str, list[str]] = scan_result.get("manifest", {})
    alias_categories = _slot_manifest_categories(category)

    candidate_ids: set[str] = set()
    for alias_category in alias_categories:
        candidate_ids.update(manifest.get(alias_category, []))

    if candidate_ids:
        candidates = [items_by_id[item_id] for item_id in sorted(candidate_ids) if item_id in items_by_id]
    else:
        source_categories = set(_slot_source_categories(category))
        candidates = []
        for item in items_by_id.values():
            path_parts = item.get("path_parts") or ["other"]
            source_category = str(path_parts[0]).lower() if path_parts else "other"
            if source_category in source_categories:
                candidates.append(item)
    if not include_custom:
        candidates = [item for item in candidates if not _is_custom_item_record(item)]
    preferred = _category_preferred_type_names(category)
    if preferred:
        preferred_candidates = [item for item in candidates if (item.get("type_name") or "").lower() in preferred]
        if preferred_candidates:
            return preferred_candidates
    return candidates


def _get_manifest_category_candidates(
    scan_result: dict[str, Any],
    category: str,
    *,
    include_custom: bool = True,
) -> list[dict[str, Any]]:
    manifest: dict[str, list[str]] = scan_result.get("manifest", {})
    items_by_id: dict[str, dict[str, Any]] = scan_result.get("items_by_id", {})
    item_ids_set: set[str] = set()
    for manifest_category in _slot_manifest_categories(category):
        item_ids_set.update(manifest.get(manifest_category, []))
    item_ids = sorted(item_ids_set)
    candidates = [items_by_id[item_id] for item_id in item_ids if item_id in items_by_id]
    if not include_custom:
        candidates = [item for item in candidates if not _is_custom_item_record(item)]
    return candidates


def _infer_prompt_extended_categories(prompt_text: str) -> list[str]:
    lowered = str(prompt_text or "").lower()
    selected: list[str] = []
    for category, keywords in PROMPT_EXTENDED_CATEGORY_KEYWORDS.items():
        if any(str(keyword).lower() in lowered for keyword in keywords):
            selected.append(category)
    return selected


def _apply_lpc_only_extended_fallback(
    *,
    validated_extended_layers: dict[str, str],
    prompt_text: str,
    scan_result: dict[str, Any],
) -> dict[str, str]:
    runtime = load_relay_config().runtime
    use_non_custom_only = bool(runtime.lpc_only_exclude_custom)
    resolved = dict(validated_extended_layers)
    resolved.pop("torso", None)
    requested_body_type = _infer_requested_body_type(prompt_text)
    profile = _build_prompt_semantic_profile(prompt_text)
    items_by_id: dict[str, dict[str, Any]] = scan_result.get("items_by_id", {})

    for category in _infer_prompt_extended_categories(prompt_text):
        existing_value = resolved.get(category)
        existing_score: float | None = None
        if existing_value:
            existing_item = items_by_id.get(existing_value)
            if existing_item and (not use_non_custom_only or not _is_custom_item_record(existing_item)):
                if requested_body_type and not _item_supports_body_type(existing_item, requested_body_type):
                    existing_value = None
                    resolved.pop(category, None)
                else:
                    existing_score = _candidate_semantic_score(
                        category=category,
                        candidate=existing_item,
                        profile=profile,
                    )
            else:
                existing_value = None
                resolved.pop(category, None)

        candidates = _get_manifest_category_candidates(
            scan_result,
            category,
            include_custom=not use_non_custom_only,
        )
        if requested_body_type:
            candidates = [
                item for item in candidates if _item_supports_body_type(item, requested_body_type)
            ]
        matched = _semantic_similarity_select(
            prompt_text=prompt_text,
            candidates=candidates,
            category=category,
        )
        if matched:
            if not existing_value:
                resolved[category] = matched
                continue
            matched_item = items_by_id.get(matched)
            matched_score = _candidate_semantic_score(
                category=category,
                candidate=matched_item or {},
                profile=profile,
            )
            if existing_score is None or matched_score >= existing_score + 0.2:
                resolved[category] = matched
    return resolved


def select_template_candidate(
    requested_internal_name: str,
    candidates: list[dict[str, Any]],
    similarity_threshold: float = 0.3,
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("No template candidates available for this category.")

    scored = []
    for candidate in candidates:
        search_text = candidate.get("search_text") or candidate.get("item_id", "")
        score = _jaccard_similarity(requested_internal_name, search_text)
        scored.append((score, candidate))

    scored.sort(key=lambda item: (item[0], item[1].get("layer_count", 0)), reverse=True)
    best_score, best_candidate = scored[0]
    if best_score >= similarity_threshold:
        selected = dict(best_candidate)
        selected["selection_reason"] = "similarity_match"
        selected["similarity_score"] = best_score
        return selected

    standard_candidates = [candidate for candidate in candidates if candidate.get("is_standard_template") is True]
    if standard_candidates:
        standard_candidates.sort(
            key=lambda candidate: (
                candidate.get("layer_count", 0),
                candidate.get("item_id", ""),
            ),
            reverse=True,
        )
        selected = dict(standard_candidates[0])
        selected["selection_reason"] = "standard_template_fallback"
        selected["similarity_score"] = best_score
        return selected

    signature_counter = Counter(tuple(candidate.get("zpos_signature", ())) for candidate in candidates)
    candidates_sorted = sorted(
        candidates,
        key=lambda candidate: (
            candidate.get("layer_count", 0),
            signature_counter[tuple(candidate.get("zpos_signature", ()))],
            candidate.get("item_id", ""),
        ),
        reverse=True,
    )
    selected = dict(candidates_sorted[0])
    selected["selection_reason"] = "most_complete_layers_fallback"
    selected["similarity_score"] = best_score
    return selected


def precheck_spritesheet_root(
    spritesheet_root_abs: Path,
    expected_animations: list[str],
) -> dict[str, Any]:
    if not spritesheet_root_abs.exists() or not spritesheet_root_abs.is_dir():
        raise ValueError(f"spritesheet_root does not exist or is not a directory: {spritesheet_root_abs}")

    png_files = sorted(spritesheet_root_abs.rglob("*.png"))
    if not png_files:
        raise ValueError("spritesheet_root contains no .png files.")

    animation_tokens = {_token for _token in (_tokenize(" ".join(expected_animations))) if _token}
    animation_hint_matched = False
    if animation_tokens:
        for png_file in png_files:
            rel = png_file.relative_to(spritesheet_root_abs).as_posix().lower()
            if any(token in rel for token in animation_tokens):
                animation_hint_matched = True
                break
        if not animation_hint_matched:
            raise ValueError(
                "PNG files found, but none match template animation hints. "
                "Ensure at least one expected animation token appears in folder/file naming."
            )

    return {
        "png_count": len(png_files),
        "animation_hint_matched": animation_hint_matched,
    }


def _safe_relative_spritesheet_path(path_text: str) -> Path:
    relative = Path(path_text.strip("/"))
    if any(part == ".." for part in relative.parts):
        raise ValueError(f"Unsafe layer path contains '..': {path_text}")
    return relative


def _decode_base64_image(image_base64: str) -> Image.Image:
    normalized = image_base64.strip()
    if normalized.startswith("data:"):
        parts = normalized.split(",", 1)
        if len(parts) != 2:
            raise ValueError("Invalid data URL image payload.")
        normalized = parts[1]

    try:
        image_bytes = base64.b64decode(normalized)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid image_base64 payload: {exc}") from exc

    try:
        return Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to decode image payload: {exc}") from exc


def _cleanup_alpha_edges(image: Image.Image, *, alpha_cutoff: int = 12) -> Image.Image:
    rgba = image.convert("RGBA")
    cleaned = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    src_pixels = rgba.load()
    dst_pixels = cleaned.load()

    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = src_pixels[x, y]
            if alpha <= alpha_cutoff:
                dst_pixels[x, y] = (0, 0, 0, 0)
            else:
                dst_pixels[x, y] = (red, green, blue, alpha)
    return cleaned


def _trim_to_subject(image: Image.Image) -> Image.Image:
    alpha = image.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("Input image has no visible (alpha>0) subject after cleanup.")
    return image.crop(bbox)


def _should_use_two_stage_downscale(width: int, height: int, tile_size: int) -> bool:
    return max(width, height) >= tile_size * 4


def _resize_subject_to_fit_tile(subject: Image.Image, tile_size: int) -> Image.Image:
    width, height = subject.size
    if width <= tile_size and height <= tile_size:
        return subject

    fit_scale = min(tile_size / width, tile_size / height)
    target_size = (
        max(1, int(round(width * fit_scale))),
        max(1, int(round(height * fit_scale))),
    )

    if _should_use_two_stage_downscale(width, height, tile_size):
        # Large-to-tiny reduction keeps structure better with a two-step strategy.
        intermediate_scale = min((tile_size * 2) / width, (tile_size * 2) / height)
        intermediate_size = (
            max(1, int(round(width * intermediate_scale))),
            max(1, int(round(height * intermediate_scale))),
        )
        return subject.resize(intermediate_size, Image.Resampling.LANCZOS).resize(
            target_size, Image.Resampling.NEAREST
        )

    return subject.resize(target_size, Image.Resampling.NEAREST)


def _resolve_canvas_alignment(
    *,
    category: str,
    preview_x_offset: int | None,
    preview_y_offset: int | None,
) -> tuple[str, int, int]:
    if preview_x_offset is not None or preview_y_offset is not None:
        return ("template_offset", int(preview_x_offset or 0), int(preview_y_offset or 0))
    if category == "weapons":
        return ("bottom_center", 0, 0)
    return ("center", 0, 0)


def compose_on_standard_square_canvas(
    *,
    subject: Image.Image,
    tile_size: int,
    category: str,
    preview_x_offset: int | None,
    preview_y_offset: int | None,
) -> Image.Image:
    canvas = Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
    mode, offset_x, offset_y = _resolve_canvas_alignment(
        category=category,
        preview_x_offset=preview_x_offset,
        preview_y_offset=preview_y_offset,
    )

    if mode == "bottom_center":
        pos_x = (tile_size - subject.width) // 2
        pos_y = tile_size - subject.height
    else:
        pos_x = (tile_size - subject.width) // 2
        pos_y = (tile_size - subject.height) // 2
        if mode == "template_offset":
            clamped_x = max(-tile_size // 2, min(tile_size // 2, offset_x))
            clamped_y = max(-tile_size // 2, min(tile_size // 2, offset_y))
            pos_x += clamped_x
            pos_y += clamped_y

    pos_x = max(-subject.width + 1, min(tile_size - 1, pos_x))
    pos_y = max(-subject.height + 1, min(tile_size - 1, pos_y))
    canvas.alpha_composite(subject, (pos_x, pos_y))
    return canvas


def _rotation_for_row(row_index: int) -> int:
    direction = ("n", "w", "s", "e")[row_index % 4]
    if direction == "w":
        return 90
    if direction == "s":
        return 180
    if direction == "e":
        return -90
    return 0


def _rotate_tile(tile: Image.Image, angle: int) -> Image.Image:
    if angle == 90:
        return tile.transpose(Image.Transpose.ROTATE_90)
    if angle == -90:
        return tile.transpose(Image.Transpose.ROTATE_270)
    if angle == 180:
        return tile.transpose(Image.Transpose.ROTATE_180)
    return tile


def expand_single_tile_to_animation_sheet(tile: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_width, target_height = target_size
    output = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))

    if target_width % tile.width != 0 or target_height % tile.height != 0:
        pos = ((target_width - tile.width) // 2, (target_height - tile.height) // 2)
        output.alpha_composite(tile, pos)
        return output

    cols = target_width // tile.width
    rows = target_height // tile.height
    for row in range(rows):
        angle = _rotation_for_row(row)
        row_tile = _rotate_tile(tile, angle)
        for col in range(cols):
            output.alpha_composite(row_tile, (col * tile.width, row * tile.height))
    return output


def _animation_folder_name(animation_name: str) -> str:
    return ANIMATION_FOLDER_ALIASES.get(animation_name, animation_name)


def _template_variant_candidates(template_definition: dict[str, Any], template_item_id: str) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []

    definition_variants = template_definition.get("variants", [])
    if isinstance(definition_variants, list):
        for variant in definition_variants:
            if isinstance(variant, str) and variant and variant not in seen:
                seen.add(variant)
                candidates.append(variant)

    fallback = template_item_id.split("_")[-1]
    if fallback and fallback not in seen:
        seen.add(fallback)
        candidates.append(fallback)

    return candidates


def _find_reference_png(
    *,
    base_rel: Path,
    animation_folder: str | None,
    variant_candidates: list[str],
) -> Path | None:
    base_dir = scanner.DEFAULT_SPRITES_ROOT / base_rel
    candidate_dir = base_dir / animation_folder if animation_folder else base_dir

    if candidate_dir.is_file() and candidate_dir.suffix.lower() == ".png":
        return candidate_dir

    for variant in variant_candidates:
        direct = candidate_dir / f"{variant}.png"
        if direct.exists():
            return direct

    for candidate in sorted(candidate_dir.glob("*.png")):
        return candidate

    for candidate in sorted(candidate_dir.rglob("*.png")):
        return candidate

    return None


def _infer_tile_size(
    *,
    sheet_size: tuple[int, int],
    custom_animation: str | None,
) -> int:
    width, height = sheet_size
    if custom_animation:
        match = re.search(r"(\d{2,3})", custom_animation)
        if match:
            size = int(match.group(1))
            if size > 0:
                return size

    for candidate in (256, 192, 160, 128, 96, 80, 64, 56, 48, 40, 32, 24, 16):
        if width % candidate == 0 and height % candidate == 0:
            cols = width // candidate
            rows = height // candidate
            if 1 <= cols <= 40 and 1 <= rows <= 80:
                return candidate

    return max(16, min(width, height))


def _build_single_image_targets(
    *,
    template_definition: dict[str, Any],
    new_definition: dict[str, Any],
    template_item_id: str,
    output_variant: str,
) -> list[dict[str, Any]]:
    variant_candidates = _template_variant_candidates(template_definition, template_item_id)
    animation_values = new_definition.get("animations", [])
    animation_folders = {
        _animation_folder_name(anim)
        for anim in animation_values
        if isinstance(anim, str) and anim
    }

    dedup: dict[str, dict[str, Any]] = {}
    for idx in range(1, 20):
        layer_key = f"layer_{idx}"
        template_layer = template_definition.get(layer_key)
        output_layer = new_definition.get(layer_key)
        if not isinstance(template_layer, dict) or not isinstance(output_layer, dict):
            break

        custom_animation = output_layer.get("custom_animation")
        custom_animation = custom_animation if isinstance(custom_animation, str) and custom_animation else None

        for body_type in BODY_TYPE_KEYS:
            template_base = template_layer.get(body_type)
            output_base = output_layer.get(body_type)
            if not isinstance(template_base, str) or not template_base:
                continue
            if not isinstance(output_base, str) or not output_base:
                continue
            if _contains_template_variable(template_base) or _contains_template_variable(output_base):
                continue

            template_base_rel = _safe_relative_spritesheet_path(template_base)
            output_base_rel = _safe_relative_spritesheet_path(output_base)

            if custom_animation:
                output_rel = output_base_rel / f"{output_variant}.png"
                reference = _find_reference_png(
                    base_rel=template_base_rel,
                    animation_folder=None,
                    variant_candidates=variant_candidates,
                )
                dedup[output_rel.as_posix()] = {
                    "output_rel": output_rel,
                    "reference_png": reference,
                    "custom_animation": custom_animation,
                }
                continue

            if not animation_folders:
                output_rel = output_base_rel / f"{output_variant}.png"
                reference = _find_reference_png(
                    base_rel=template_base_rel,
                    animation_folder=None,
                    variant_candidates=variant_candidates,
                )
                dedup[output_rel.as_posix()] = {
                    "output_rel": output_rel,
                    "reference_png": reference,
                    "custom_animation": None,
                }
                continue

            for animation_folder in sorted(animation_folders):
                output_rel = output_base_rel / animation_folder / f"{output_variant}.png"
                reference = _find_reference_png(
                    base_rel=template_base_rel,
                    animation_folder=animation_folder,
                    variant_candidates=variant_candidates,
                )
                key = output_rel.as_posix()
                existing = dedup.get(key)
                if existing and existing.get("reference_png"):
                    continue
                dedup[key] = {
                    "output_rel": output_rel,
                    "reference_png": reference,
                    "custom_animation": None,
                }

    targets = sorted(dedup.values(), key=lambda item: item["output_rel"].as_posix())
    if not targets:
        raise ValueError("No writable output targets could be built from template layers.")
    return targets


def _write_single_image_assets(
    *,
    image_base64: str,
    category: str,
    template_definition: dict[str, Any],
    new_definition: dict[str, Any],
    template_item_id: str,
    output_variant: str,
) -> list[str]:
    raw_image = _decode_base64_image(image_base64)
    cleaned = _cleanup_alpha_edges(raw_image, alpha_cutoff=12)
    subject = _trim_to_subject(cleaned)

    preview_x_offset = template_definition.get("preview_x_offset")
    preview_y_offset = template_definition.get("preview_y_offset")
    if not isinstance(preview_x_offset, int):
        preview_x_offset = None
    if not isinstance(preview_y_offset, int):
        preview_y_offset = None

    targets = _build_single_image_targets(
        template_definition=template_definition,
        new_definition=new_definition,
        template_item_id=template_item_id,
        output_variant=output_variant,
    )

    tile_cache: dict[int, Image.Image] = {}
    sheet_cache: dict[tuple[int, int, int], Image.Image] = {}
    reference_size_cache: dict[str, tuple[int, int]] = {}
    written: list[str] = []

    for target in targets:
        output_rel = target["output_rel"]
        output_abs = scanner.DEFAULT_SPRITES_ROOT / output_rel
        if output_abs.exists():
            raise ValueError(f"Target sprite file already exists: {output_rel.as_posix()}")

        reference_png = target.get("reference_png")
        if not isinstance(reference_png, Path) or not reference_png.exists():
            raise ValueError(
                f"Unable to locate template reference PNG for target path: {output_rel.as_posix()}"
            )

        ref_key = str(reference_png)
        if ref_key not in reference_size_cache:
            with Image.open(reference_png) as ref_img:
                reference_size_cache[ref_key] = ref_img.size
        target_size = reference_size_cache[ref_key]
        tile_size = _infer_tile_size(sheet_size=target_size, custom_animation=target.get("custom_animation"))

        if tile_size not in tile_cache:
            resized_subject = _resize_subject_to_fit_tile(subject, tile_size)
            tile_cache[tile_size] = compose_on_standard_square_canvas(
                subject=resized_subject,
                tile_size=tile_size,
                category=category,
                preview_x_offset=preview_x_offset,
                preview_y_offset=preview_y_offset,
            )

        sheet_key = (tile_size, target_size[0], target_size[1])
        if sheet_key not in sheet_cache:
            sheet_cache[sheet_key] = expand_single_tile_to_animation_sheet(
                tile_cache[tile_size], target_size
            )

        output_abs.parent.mkdir(parents=True, exist_ok=True)
        sheet_cache[sheet_key].save(output_abs, format="PNG")
        written.append(str(output_abs))

    return written


def _cleanup_written_files(paths: list[str]) -> None:
    for path_text in paths:
        file_path = Path(path_text)
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            continue


def _build_backup_files() -> list[str]:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = BACKUP_ROOT / f"register_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_files: list[str] = []
    for filename in ("item-metadata.js", "CREDITS.csv"):
        source_file = GENERATOR_DIR / filename
        if source_file.exists():
            destination_file = backup_dir / filename
            shutil.copy2(source_file, destination_file)
            backup_files.append(str(destination_file))
    return backup_files


def _run_generate_sources() -> None:
    try:
        result = subprocess.run(
            ["node", "scripts/generate_sources.js"],
            cwd=GENERATOR_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Node.js is required but not found in PATH.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        raise HTTPException(
            status_code=500,
            detail=f"Metadata rebuild failed. stdout={stdout[:400]} stderr={stderr[:400]}",
        ) from exc

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail="Metadata rebuild failed unexpectedly.")


def _definition_directory_for_category(category: str) -> Path:
    if category == "body":
        return GENERATOR_DIR / "sheet_definitions" / "body" / "custom"
    if category == "hair":
        return GENERATOR_DIR / "sheet_definitions" / "hair" / "custom"
    if category == "armor":
        return GENERATOR_DIR / "sheet_definitions" / "torso" / "armour" / "custom"
    if category == "weapons":
        return GENERATOR_DIR / "sheet_definitions" / "weapons" / "custom"
    raise ValueError(f"Unsupported category: {category}")


def _replace_prefix(path_text: str, old_prefix: str, new_prefix: str) -> str:
    old_norm = old_prefix.strip("/")
    new_norm = new_prefix.strip("/")
    value_norm = path_text.strip("/")

    if not old_norm:
        raise ValueError("Template base prefix is empty; cannot rewrite layer paths safely.")
    if _contains_template_variable(path_text):
        return path_text
    if not value_norm.startswith(old_norm):
        raise ValueError(f"Layer path '{path_text}' does not start with template prefix '{old_prefix}'.")

    suffix = value_norm[len(old_norm) :].lstrip("/")
    replaced = f"{new_norm}/{suffix}" if suffix else new_norm
    if path_text.endswith("/"):
        return replaced.rstrip("/") + "/"
    return replaced


def _contains_template_variable(path_text: str) -> bool:
    return "${" in path_text


def _rewrite_definition_for_registration(
    *,
    template_definition: dict[str, Any],
    template_prefix: str,
    new_prefix: str,
    internal_name: str,
    display_name: str,
    category: str,
) -> dict[str, Any]:
    cloned = json.loads(json.dumps(template_definition))

    cloned["name"] = display_name
    cloned["is_standard_template"] = False

    category_type_name_map = {
        "body": "body",
        "hair": "hair",
        "armor": "armour",
        "weapons": "weapon",
    }
    if category in category_type_name_map:
        cloned["type_name"] = category_type_name_map[category]

    for idx in range(1, 20):
        layer_key = f"layer_{idx}"
        layer = cloned.get(layer_key)
        if not isinstance(layer, dict):
            break
        for key, value in list(layer.items()):
            if key in scanner.LAYER_META_KEYS:
                continue
            if isinstance(value, str) and value:
                layer[key] = _replace_prefix(value, template_prefix, new_prefix)

    credits = cloned.get("credits", [])
    if isinstance(credits, list):
        for credit in credits:
            if not isinstance(credit, dict):
                continue
            file_value = credit.get("file")
            if isinstance(file_value, str) and file_value:
                if file_value.strip("/").startswith(template_prefix.strip("/")):
                    credit["file"] = _replace_prefix(file_value, template_prefix, new_prefix)

    path_value = cloned.get("path")
    if isinstance(path_value, list) and path_value:
        path_value[-1] = internal_name
    else:
        if category == "armor":
            cloned["path"] = ["torso", "armour", "custom", internal_name]
        elif category == "weapons":
            cloned["path"] = ["weapons", "custom", internal_name]
        else:
            cloned["path"] = [category, "custom", internal_name]

    cloned["variants"] = [internal_name]

    return cloned


def _normalize_http_error_detail(exc: HTTPException) -> str:
    if isinstance(exc.detail, str):
        return exc.detail
    return json.dumps(exc.detail, ensure_ascii=True)


def _run_analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    gen_mode_enabled = resolve_gen_mode(payload.gen_mode)
    scan_result, _ = _refresh_manifest()
    runtime = load_relay_config().runtime
    manifest_context_json = _build_manifest_context_for_prompt(
        scan_result,
        prompt_text=payload.prompt,
        include_custom=bool(gen_mode_enabled) or not bool(runtime.lpc_only_exclude_custom),
    )
    system_prompt = _build_analyze_system_prompt(manifest_context_json, gen_mode_enabled=gen_mode_enabled)

    llm_output: AnalyzeLLMOutput
    try:
        raw_text = call_gemini_relay(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload.prompt},
            ],
            require_json_response=True,
            temperature=0.1,
        )
        sanitized_text = _sanitize_json_text(raw_text)
        llm_payload = json.loads(sanitized_text)
        llm_output = AnalyzeLLMOutput.model_validate(llm_payload)
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, json.JSONDecodeError):
            raise HTTPException(status_code=502, detail=f"Analyze response is not valid JSON: {exc}") from exc
        raise HTTPException(status_code=502, detail=f"Analyze response schema mismatch: {exc}") from exc

    validated_layers = _validate_selected_layers(llm_output.selected_layers, scan_result["manifest"])
    validated_extended_layers = _validate_extended_layers(llm_output.extended_layers, scan_result["items_by_id"])
    requested_body_type = _infer_requested_body_type(payload.prompt)
    validated_layers, validated_extended_layers = _filter_incompatible_layers_by_body_type(
        selected_layers=validated_layers,
        extended_layers=validated_extended_layers,
        scan_result=scan_result,
        requested_body_type=requested_body_type,
    )
    validated_extended_layers = _dedupe_overlapping_layers(validated_layers, validated_extended_layers)
    generation_tasks_dump = [task.model_dump() for task in llm_output.generation_tasks]
    missing_assets_dump = build_missing_assets(generation_tasks_dump)

    if not gen_mode_enabled:
        merged_prompt = f"{payload.prompt} {llm_output.character_summary}".strip()
        finalized_layers = _apply_lpc_only_fallback(
            validated_layers=validated_layers,
            prompt_text=merged_prompt,
            scan_result=scan_result,
        )
        finalized_extended_layers = _apply_lpc_only_extended_fallback(
            validated_extended_layers=validated_extended_layers,
            prompt_text=merged_prompt,
            scan_result=scan_result,
        )
        finalized_extended_layers = _dedupe_overlapping_layers(finalized_layers, finalized_extended_layers)
        return AnalyzeResponse(
            mode_resolved=_mode_label(gen_mode_enabled),
            character_summary=llm_output.character_summary,
            selected_layers=finalized_layers,
            extended_layers=finalized_extended_layers,
            generation_tasks=[],
            missing_assets=[],
            is_complete=True,
            manifest_refreshed_at=datetime.now(tz=UTC).isoformat(),
            warnings_count=len(scan_result.get("warnings", [])),
        )

    missing_assets = [MissingAsset.model_validate(item) for item in missing_assets_dump]
    complete = bool(llm_output.is_complete and not missing_assets)
    return AnalyzeResponse(
        mode_resolved=_mode_label(gen_mode_enabled),
        character_summary=llm_output.character_summary,
        selected_layers=validated_layers,
        extended_layers=validated_extended_layers,
        generation_tasks=llm_output.generation_tasks,
        missing_assets=missing_assets,
        is_complete=complete,
        manifest_refreshed_at=datetime.now(tz=UTC).isoformat(),
        warnings_count=len(scan_result.get("warnings", [])),
    )


def _next_available_internal_name(
    *,
    base_name: str,
    category: str,
    existing_names: set[str],
) -> str:
    candidate = _normalize_internal_name(base_name)
    if candidate not in existing_names:
        existing_names.add(candidate)
        return candidate

    index = 2
    while True:
        scoped = f"{candidate}_v{index}"
        if scoped not in existing_names:
            existing_names.add(scoped)
            return scoped
        index += 1


def _register_generated_asset_core(
    payload: RegisterGeneratedAssetRequest,
    *,
    gen_mode_enabled: bool,
) -> RegisterGeneratedAssetResponse:
    if payload.image_base64 and not gen_mode_enabled:
        raise HTTPException(
            status_code=422,
            detail="GEN mode is OFF. image_base64 registration is disabled in LPC-only mode.",
        )

    internal_name = _normalize_internal_name(payload.internal_name)
    display_name = payload.display_name.strip() if payload.display_name else _to_title_case_from_internal_name(internal_name)

    scan_result, _ = _refresh_manifest()
    candidates = _get_category_candidates(scan_result, payload.category)

    if payload.template_item_id:
        template = next((candidate for candidate in candidates if candidate["item_id"] == payload.template_item_id), None)
        if not template:
            raise HTTPException(
                status_code=422,
                detail=f"template_item_id '{payload.template_item_id}' is not valid for category '{payload.category}'.",
            )
        selected_template = dict(template)
        selected_template["selection_reason"] = "explicit_template"
    else:
        try:
            selected_template = select_template_candidate(internal_name, candidates, similarity_threshold=0.3)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    template_definition_path = ROOT_DIR / selected_template["relative_definition_file"]
    if not template_definition_path.exists():
        raise HTTPException(status_code=422, detail="Selected template definition file does not exist.")

    try:
        template_definition = json.loads(template_definition_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Template definition JSON is invalid: {exc}") from exc

    template_prefix = selected_template.get("template_base_prefix") or ""
    if not template_prefix:
        raise HTTPException(status_code=422, detail="Template is missing a usable base prefix for layer path rewriting.")

    spritesheet_root_rel = payload.spritesheet_root.strip().strip("/")
    if not spritesheet_root_rel:
        raise HTTPException(status_code=422, detail="spritesheet_root is empty after normalization.")
    spritesheet_root_abs = scanner.DEFAULT_SPRITES_ROOT / spritesheet_root_rel

    try:
        new_definition = _rewrite_definition_for_registration(
            template_definition=template_definition,
            template_prefix=template_prefix,
            new_prefix=spritesheet_root_rel,
            internal_name=internal_name,
            display_name=display_name,
            category=payload.category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    created_sprite_files: list[str] = []
    if payload.image_base64:
        try:
            created_sprite_files = _write_single_image_assets(
                image_base64=payload.image_base64,
                category=payload.category,
                template_definition=template_definition,
                new_definition=new_definition,
                template_item_id=selected_template["item_id"],
                output_variant=internal_name,
            )
        except ValueError as exc:
            _cleanup_written_files(created_sprite_files)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            _cleanup_written_files(created_sprite_files)
            raise HTTPException(status_code=500, detail=f"Single-image processing failed: {exc}") from exc

    try:
        precheck = precheck_spritesheet_root(spritesheet_root_abs, list(selected_template.get("animations", [])))
    except ValueError as exc:
        _cleanup_written_files(created_sprite_files)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    definition_dir = _definition_directory_for_category(payload.category)
    definition_dir.mkdir(parents=True, exist_ok=True)
    output_file = definition_dir / f"{internal_name}.json"
    if output_file.exists():
        _cleanup_written_files(created_sprite_files)
        raise HTTPException(status_code=409, detail=f"Definition already exists: {output_file.name}")

    backup_files = _build_backup_files()

    try:
        output_file.write_text(json.dumps(new_definition, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        _run_generate_sources()
        scanner.write_manifest(
            output_path=MANIFEST_PATH,
            definitions_root=scanner.DEFAULT_DEFINITIONS_ROOT,
            sprites_root=scanner.DEFAULT_SPRITES_ROOT,
        )
    except Exception:
        if output_file.exists():
            output_file.unlink()
        _cleanup_written_files(created_sprite_files)
        raise

    return RegisterGeneratedAssetResponse(
        definition_file=str(output_file),
        template_used=selected_template["item_id"],
        selection_reason=str(selected_template.get("selection_reason", "unknown")),
        precheck=PrecheckResult.model_validate(precheck),
        single_image_processed=bool(payload.image_base64),
        generated_png_files=len(created_sprite_files),
        metadata_rebuilt=True,
        backup_files=backup_files,
        manifest_updated=True,
    )


def _compute_execute_overall_status(results: list[GeneratedAssetResult], *, auto_register: bool) -> Literal["success", "partial_success", "failed"]:
    if not results:
        return "success"

    if auto_register:
        success_count = sum(1 for item in results if item.register_status == "succeeded")
    else:
        success_count = sum(1 for item in results if item.image_status == "succeeded")

    if success_count == len(results):
        return "success"
    if success_count == 0:
        return "failed"
    return "partial_success"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ai/text", response_model=TextResponse)
def ai_text(payload: TextRequest) -> TextResponse:
    output_text = call_gemini_relay(
        messages=[{"role": "user", "content": payload.prompt}],
        require_json_response=False,
    )
    return TextResponse(output=output_text.strip())


@app.post("/ai/analyze", response_model=AnalyzeResponse)
def ai_analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    return _run_analyze(payload)


@app.post("/ai/execute", response_model=ExecuteResponse)
def ai_execute(payload: ExecuteRequest) -> ExecuteResponse:
    gen_mode_enabled = resolve_gen_mode(payload.gen_mode)
    analysis_before = _run_analyze(
        AnalyzeRequest(
            prompt=payload.prompt,
            gen_mode=gen_mode_enabled,
        )
    )

    if not gen_mode_enabled:
        return ExecuteResponse(
            mode_resolved="LPC_ONLY",
            overall_status="success",
            analysis_before=analysis_before,
            generated_assets=[],
            analysis_after=analysis_before,
            errors=[],
        )

    runtime = load_relay_config().runtime
    max_tasks = payload.max_generation_tasks if payload.max_generation_tasks is not None else runtime.max_generation_tasks
    max_tasks = max(1, int(max_tasks))
    tasks = list(analysis_before.missing_assets[:max_tasks])

    scan_result, _ = _refresh_manifest()
    existing_names = set(scan_result["manifest"].get("body", []))
    existing_names.update(scan_result["manifest"].get("hair", []))
    existing_names.update(scan_result["manifest"].get("armor", []))
    existing_names.update(scan_result["manifest"].get("weapons", []))

    generated_assets: list[GeneratedAssetResult] = []
    errors: list[str] = []
    any_registered = False

    for task in tasks:
        task_category = str(task.category or "").strip().lower()
        if task_category not in {"body", "hair", "armor", "weapons"}:
            message = f"[{task.category}/{task.internal_name}] unsupported category; skipped."
            errors.append(message)
            generated_assets.append(
                GeneratedAssetResult(
                    category=str(task.category),
                    internal_name=str(task.internal_name),
                    image_status="skipped",
                    register_status="skipped",
                    image_error=message,
                )
            )
            continue

        try:
            requested_name = _normalize_internal_name(task.internal_name)
        except ValueError as exc:
            message = f"[{task_category}/{task.internal_name}] invalid internal_name: {exc}"
            errors.append(message)
            generated_assets.append(
                GeneratedAssetResult(
                    category=task_category,
                    internal_name=str(task.internal_name),
                    image_status="skipped",
                    register_status="skipped",
                    image_error=message,
                )
            )
            continue

        unique_name = _next_available_internal_name(
            base_name=requested_name,
            category=task_category,
            existing_names=existing_names,
        )
        result = GeneratedAssetResult(
            category=task_category,
            internal_name=unique_name,
            image_status="skipped",
            register_status="skipped",
        )

        prompt_for_image = (task.visual_prompt or "").strip()
        if not prompt_for_image:
            message = f"[{task.category}/{unique_name}] missing visual_prompt; skipped image generation."
            errors.append(message)
            result.image_status = "failed"
            result.image_error = message
            generated_assets.append(result)
            continue

        try:
            image_base64 = call_image_relay(prompt_for_image, size="1:1", n=1)
            result.image_status = "succeeded"
        except Exception as exc:  # noqa: BLE001
            message = f"[{task.category}/{unique_name}] image generation failed: {exc}"
            errors.append(message)
            result.image_status = "failed"
            result.image_error = message
            generated_assets.append(result)
            continue

        if not payload.auto_register:
            result.register_status = "skipped"
            generated_assets.append(result)
            continue

        try:
            register_response = _register_generated_asset_core(
                RegisterGeneratedAssetRequest(
                    category=task_category,
                    internal_name=unique_name,
                    display_name=None,
                    spritesheet_root=f"ai_generated/{task_category}/{unique_name}",
                    template_item_id=None,
                    gen_mode=True,
                    image_base64=image_base64,
                ),
                gen_mode_enabled=True,
            )
            result.register_status = "succeeded"
            result.definition_file = register_response.definition_file
            any_registered = True
        except HTTPException as exc:
            message = f"[{task.category}/{unique_name}] register failed: {_normalize_http_error_detail(exc)}"
            errors.append(message)
            result.register_status = "failed"
            result.register_error = message
        except Exception as exc:  # noqa: BLE001
            message = f"[{task.category}/{unique_name}] register failed: {exc}"
            errors.append(message)
            result.register_status = "failed"
            result.register_error = message

        generated_assets.append(result)

    analysis_after: AnalyzeResponse | None = None
    if payload.auto_register and any_registered:
        analysis_after = _run_analyze(
            AnalyzeRequest(
                prompt=payload.prompt,
                gen_mode=True,
            )
        )

    overall_status = _compute_execute_overall_status(generated_assets, auto_register=payload.auto_register)
    return ExecuteResponse(
        mode_resolved="GEN",
        overall_status=overall_status,
        analysis_before=analysis_before,
        generated_assets=generated_assets,
        analysis_after=analysis_after,
        errors=errors,
    )


@app.post("/assets/register-generated", response_model=RegisterGeneratedAssetResponse)
def register_generated_asset(payload: RegisterGeneratedAssetRequest) -> RegisterGeneratedAssetResponse:
    gen_mode_enabled = resolve_gen_mode(payload.gen_mode)
    return _register_generated_asset_core(payload, gen_mode_enabled=gen_mode_enabled)


@app.get("/assets/lookup/{item_id}", response_model=AssetLookupResponse)
def lookup_asset(item_id: str) -> AssetLookupResponse:
    scan_result, _ = _refresh_manifest()
    item = scan_result["items_by_id"].get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Asset item_id '{item_id}' not found in manifest scan.")

    definition_file = str(item.get("definition_file", ""))
    is_custom = _is_custom_item_record(item)

    return AssetLookupResponse(
        item_id=item["item_id"],
        category=item.get("primary_category") or "other",
        is_custom=is_custom,
        definition_file=definition_file,
        display_name=item.get("display_name") or item["item_id"],
        type_name=item.get("type_name"),
    )


@app.get("/assets/capability-report")
def capability_report() -> dict[str, Any]:
    scan_result, _ = _refresh_manifest()
    summary = scan_result.get("summary", {})
    manifest = scan_result.get("manifest", {})
    items_by_id = scan_result.get("items_by_id", {})

    weapons = [item for item in items_by_id.values() if item.get("primary_category") == "weapons"]
    weapon_tag_counts: Counter[str] = Counter()
    for item in weapons:
        for tag in item.get("semantic_tags", []):
            if str(tag).startswith("weapon."):
                weapon_tag_counts[str(tag)] += 1

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "summary": summary,
        "core_category_counts": {
            "body": len(manifest.get("body", [])),
            "hair": len(manifest.get("hair", [])),
            "armor": len(manifest.get("armor", [])),
            "weapons": len(manifest.get("weapons", [])),
        },
        "weapon_capabilities": weapon_tag_counts.most_common(30),
        "catalog_path": str(ASSET_CATALOG_PATH),
    }


@app.get("/assets/vector-report")
def vector_report() -> dict[str, Any]:
    scan_result, _ = _refresh_manifest()
    index_payload = _load_vector_index_or_build(scan_result)
    categories = index_payload.get("categories", {})
    if not isinstance(categories, dict):
        categories = {}
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "index_path": str(VECTOR_INDEX_PATH),
        "doc_count": int(index_payload.get("doc_count", 0) or 0),
        "source_category_counts": {
            category: len(items) for category, items in sorted(categories.items(), key=lambda item: item[0])
        },
    }


@app.post("/ai/remove-background", response_model=RemoveBgResponse)
def ai_remove_background(payload: RemoveBgRequest) -> RemoveBgResponse:
    if rembg_remove is None:
        raise HTTPException(
            status_code=503,
            detail="rembg is not installed. Install it to use /ai/remove-background.",
        )

    try:
        image_bytes = base64.b64decode(payload.image_base64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid base64 input: {exc}") from exc

    try:
        input_image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        output_image = rembg_remove(input_image)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Background removal failed: {exc}") from exc

    output_buffer = io.BytesIO()
    output_image.save(output_buffer, format="PNG")
    output_base64 = base64.b64encode(output_buffer.getvalue()).decode("utf-8")
    return RemoveBgResponse(image_base64=output_base64)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
