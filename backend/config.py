"""Loads `config.yaml` (everything tunable) and `.env` (secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from dotenv import load_dotenv

from backend.agent.triggers import TriggerConfig

ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """Misconfiguration that must stop the backend from starting."""


@dataclass(frozen=True)
class ModelIds:
    prep: str
    interviewer: str
    report: str


@dataclass(frozen=True)
class RunnerConfig:
    python: str = "python3"
    timeout_s: float = 10
    memory_mb: int = 512
    output_cap_kb: int = 64


TtsEngine = Literal["browser", "off"]


@dataclass(frozen=True)
class VoiceConfig:
    """`config.yaml` `voice`: what the browser's voice layer needs, stored in each Session's
    settings."""

    utterance_silence_ms: int = 1200
    """Interim speech with no new result for this long ends the utterance."""
    tts: TtsEngine = "browser"
    """The Interviewer's voice: the browser's speech synthesis, or `off` (text only)."""
    tts_voice: str | None = None
    """A speech-synthesis voice name (as the browser lists it); None is the browser default."""
    tts_rate: float = 1.0
    pause_stt_during_tts: bool = False
    """Fallback for speakers: stop listening while the Interviewer speaks (disables barge-in)."""

    def to_settings(self) -> dict[str, Any]:
        return {
            "utterance_silence_ms": self.utterance_silence_ms,
            "tts": self.tts,
            "tts_voice": self.tts_voice,
            "tts_rate": self.tts_rate,
            "pause_stt_during_tts": self.pause_stt_during_tts,
        }

    @classmethod
    def from_config(cls, value: dict[str, Any] | None) -> VoiceConfig:
        value, default = value or {}, cls()
        tts = value.get("tts", default.tts)
        if tts not in get_args(TtsEngine):
            raise ConfigError(f"voice.tts must be one of {list(get_args(TtsEngine))}, not {tts!r}")
        voice = value.get("tts_voice")
        return cls(
            utterance_silence_ms=int(
                value.get("utterance_silence_ms", default.utterance_silence_ms)
            ),
            tts=tts,
            tts_voice=str(voice) if voice else None,
            tts_rate=float(value.get("tts_rate", default.tts_rate)),
            pause_stt_during_tts=bool(
                value.get("pause_stt_during_tts", default.pause_stt_during_tts)
            ),
        )


@dataclass(frozen=True)
class Config:
    api_key: str
    models: ModelIds
    default_duration_min: int
    timeout_grace_s: int
    user_phase_lock_s: int
    db_path: Path
    runner: RunnerConfig
    triggers: TriggerConfig
    voice: VoiceConfig
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
    runner_raw = raw.get("runner", {})
    interview = raw.get("interview", {})
    return Config(
        api_key=api_key,
        models=ModelIds(
            prep=models["prep"], interviewer=models["interviewer"], report=models["report"]
        ),
        default_duration_min=int(raw.get("interview", {}).get("default_duration_min", 45)),
        timeout_grace_s=int(raw.get("interview", {}).get("timeout_grace_s", 60)),
        user_phase_lock_s=int(raw.get("interview", {}).get("user_phase_lock_s", 120)),
        db_path=db_path if db_path.is_absolute() else ROOT / db_path,
        runner=RunnerConfig(
            python=str(runner_raw.get("python", "python3")),
            timeout_s=float(runner_raw.get("timeout_s", 10)),
            memory_mb=int(runner_raw.get("memory_mb", 512)),
            output_cap_kb=int(runner_raw.get("output_cap_kb", 64)),
        ),
        triggers=TriggerConfig.from_settings(interview),
        voice=VoiceConfig.from_config(raw.get("voice")),
        raw=raw,
    )
