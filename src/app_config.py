from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


@dataclass
class AppConfig:
    provider: str = "Ollama"
    ollama_host: str = "http://localhost:11434"
    gemini_model: str = DEFAULT_GEMINI_MODEL
    theme: str = "Light"


def config_path() -> Path:
    override = os.getenv("EXAMPREP_CONFIG_DIR", "").strip()
    if override:
        base = Path(override)
    else:
        base = Path(os.getenv("APPDATA", Path.home())) / "ExamPrepAI"
    return base / "config.json"


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()

    defaults = asdict(AppConfig())
    values = {key: raw.get(key, default) for key, default in defaults.items()}
    config = AppConfig(**values)
    if config.provider not in {"Ollama", "Gemini"}:
        config.provider = "Ollama"
    if config.theme not in {"Light", "Dark"}:
        config.theme = "Light"
    if config.gemini_model in {"gemini-flash-latest", "gemini-pro", ""}:
        config.gemini_model = DEFAULT_GEMINI_MODEL
    return config


def save_config(config: AppConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    temporary.replace(path)
    return path
