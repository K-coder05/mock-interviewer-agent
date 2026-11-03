"""Loads `config.yaml` (everything tunable) and `.env` (secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """Misconfiguration that must stop the backend from starting."""


@dataclass(frozen=True)
class ModelIds:
    prep: str
    interviewer: str
    report: str


@dataclass(frozen=True)
class Config:
    api_key: str
    models: ModelIds
    default_duration_min: int
    db_path: Path
    raw: dict[str, Any]
    """The full parsed config.yaml, for sections later modules read (runner, voice, ...)."""


def load_config(
    config_path: Path = ROOT / "config.yaml", env_file: Path = ROOT / ".env"
) -> Config:
    load_dotenv(env_file, override=False)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and set "
            "ANTHROPIC_API_KEY=<your key>, or export it in your shell."
        )
    try:
        raw: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {config_path}") from exc

    models = raw.get("models", {})
    db_path = Path(raw.get("storage", {}).get("db_path", "data/interviews.db"))
    return Config(
        api_key=api_key,
        models=ModelIds(
            prep=models["prep"], interviewer=models["interviewer"], report=models["report"]
        ),
        default_duration_min=int(raw.get("interview", {}).get("default_duration_min", 45)),
        db_path=db_path if db_path.is_absolute() else ROOT / db_path,
        raw=raw,
    )
