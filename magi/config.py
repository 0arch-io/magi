"""Persistent config at ~/.config/magi/config.toml. CLI flags always win."""

import tomllib
from pathlib import Path
from typing import Any

from magi.personas import SPECIALIST_DEFAULT_MODELS, SPECIALIST_NAMES

CONFIG_DIR = Path.home() / ".config" / "magi"
CONFIG_PATH = CONFIG_DIR / "config.toml"

_EXAMPLE_CONFIG = """\
# MAGI configuration
# CLI flags and env vars override these values.

[models]
# melchior = "qwen2.5:7b"
# balthasar = "qwen3:4b"
# casper = "mistral:latest"

[specialists]
# Auto-invite these specialists into every deliberation.
# invite = ["banker"]

# Override specialist models:
# [specialists.models]
# banker = "qwen2.5:7b"
# therapist = "mistral:latest"

[options]
# classifier_model = "qwen3:4b"
# max_rounds = 3
"""


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def apply_config(
    models: dict[str, str],
    cli_overrides: dict[str, str | None],
) -> tuple[dict[str, str], list[str]]:
    """Merge config file → CLI overrides into final model dict.
    Returns (models, auto_invite_specialists)."""
    cfg = load_config()

    cfg_models = cfg.get("models", {})
    for name in ("melchior", "balthasar", "casper"):
        canonical = name.upper()
        if canonical in models and cfg_models.get(name):
            models[canonical] = cfg_models[name]

    for key, val in cli_overrides.items():
        if val is not None:
            models[key.upper()] = val

    auto_invite: list[str] = []
    specialists_cfg = cfg.get("specialists", {})
    for spec_name in specialists_cfg.get("invite", []):
        canonical = spec_name.upper()
        if canonical in SPECIALIST_NAMES and canonical not in models:
            spec_models = specialists_cfg.get("models", {})
            models[canonical] = spec_models.get(spec_name, SPECIALIST_DEFAULT_MODELS.get(canonical, "qwen2.5:7b"))
            auto_invite.append(canonical)

    return models, auto_invite


def init_config() -> bool:
    """Write example config if it doesn't exist. Returns True if created."""
    if CONFIG_PATH.exists():
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_EXAMPLE_CONFIG)
    return True


def config_path_display() -> str:
    return str(CONFIG_PATH)
