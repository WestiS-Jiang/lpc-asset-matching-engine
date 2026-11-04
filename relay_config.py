import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "service_config.json"


@dataclass(frozen=True)
class RelayEndpointConfig:
    url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class RelayConfig:
    llm: RelayEndpointConfig
    image: RelayEndpointConfig
    runtime: "RuntimeConfig"
    tls: "TlsConfig"


@dataclass(frozen=True)
class RuntimeConfig:
    gen_mode_default: bool
    max_generation_tasks: int
    lpc_only_exclude_custom: bool


@dataclass(frozen=True)
class TlsConfig:
    verify: bool
    ca_bundle: str


def _read_config_file(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}

    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file: {config_path}") from exc


def _pick(config_block: dict[str, Any], key: str, env_names: list[str], default: str = "") -> str:
    value = config_block.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()

    for env_name in env_names:
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            return env_value

    return default


def _pick_bool(config_block: dict[str, Any], key: str, env_names: list[str], default: bool) -> bool:
    raw_value = config_block.get(key)
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        value = raw_value.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False

    for env_name in env_names:
        env_value = os.getenv(env_name, "").strip().lower()
        if env_value in {"1", "true", "yes", "on"}:
            return True
        if env_value in {"0", "false", "no", "off"}:
            return False
    return default


def _pick_int(config_block: dict[str, Any], key: str, env_names: list[str], default: int) -> int:
    raw_value = config_block.get(key)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return int(raw_value.strip())
        except ValueError:
            pass

    for env_name in env_names:
        env_value = os.getenv(env_name, "").strip()
        if not env_value:
            continue
        try:
            return int(env_value)
        except ValueError:
            continue
    return default


def load_relay_config(config_path: Path | None = None) -> RelayConfig:
    config_path = config_path or DEFAULT_CONFIG_PATH
    payload = _read_config_file(config_path)

    llm_block = payload.get("llm", {}) if isinstance(payload, dict) else {}
    image_block = payload.get("image", {}) if isinstance(payload, dict) else {}
    runtime_block = payload.get("runtime", {}) if isinstance(payload, dict) else {}
    tls_block = payload.get("tls", {}) if isinstance(payload, dict) else {}

    if not isinstance(llm_block, dict):
        llm_block = {}
    if not isinstance(image_block, dict):
        image_block = {}
    if not isinstance(runtime_block, dict):
        runtime_block = {}
    if not isinstance(tls_block, dict):
        tls_block = {}

    llm = RelayEndpointConfig(
        url=_pick(
            llm_block,
            key="url",
            env_names=["LLM_RELAY_URL", "GEMINI_RELAY_URL"],
            default="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        ),
        api_key=_pick(
            llm_block,
            key="api_key",
            env_names=["LLM_RELAY_API_KEY", "GEMINI_API_KEY"],
        ),
        model=_pick(
            llm_block,
            key="model",
            env_names=["LLM_RELAY_MODEL", "GEMINI_MODEL"],
            default="gemini-2.0-flash",
        ),
    )

    image = RelayEndpointConfig(
        url=_pick(
            image_block,
            key="url",
            env_names=["IMAGE_RELAY_URL"],
            default="",
        ),
        api_key=_pick(
            image_block,
            key="api_key",
            env_names=["IMAGE_RELAY_API_KEY"],
            default="",
        ),
        model=_pick(
            image_block,
            key="model",
            env_names=["IMAGE_RELAY_MODEL"],
            default="gpt-image-1",
        ),
    )

    runtime = RuntimeConfig(
        gen_mode_default=_pick_bool(
            runtime_block,
            key="gen_mode_default",
            env_names=["GEN_MODE_DEFAULT"],
            default=False,
        ),
        max_generation_tasks=max(
            1,
            _pick_int(
                runtime_block,
                key="max_generation_tasks",
                env_names=["GEN_MAX_GENERATION_TASKS"],
                default=2,
            ),
        ),
        lpc_only_exclude_custom=_pick_bool(
            runtime_block,
            key="lpc_only_exclude_custom",
            env_names=["LPC_ONLY_EXCLUDE_CUSTOM"],
            default=True,
        ),
    )

    tls = TlsConfig(
        verify=_pick_bool(
            tls_block,
            key="verify",
            env_names=["RELAY_SSL_VERIFY"],
            default=True,
        ),
        ca_bundle=_pick(
            tls_block,
            key="ca_bundle",
            env_names=["RELAY_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"],
            default="",
        ),
    )

    return RelayConfig(llm=llm, image=image, runtime=runtime, tls=tls)
