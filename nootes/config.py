"""Configuration loading from .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class NootesConfig:
    """Immutable configuration for nootes."""

    watch_dir: Path
    openai_api_key: str
    github_repo: str | None = None
    openai_model: str = "gpt-5-nano"
    nootes_dir: Path = field(init=False)
    categories_file: Path = field(init=False)
    pid_file: Path = field(init=False)
    log_file: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "nootes_dir", self.watch_dir / ".nootes")
        object.__setattr__(self, "categories_file", self.nootes_dir / "categories.json")
        object.__setattr__(self, "pid_file", self.nootes_dir / "nootes.pid")
        object.__setattr__(self, "log_file", self.nootes_dir / "nootes.log")


def load_config(env_path: Path | None = None) -> NootesConfig:
    """Load configuration from .env file."""
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    watch_dir_str = os.getenv("NOOTES_WATCH_DIR")
    if not watch_dir_str:
        raise SystemExit("Error: NOOTES_WATCH_DIR not set in .env or environment.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Error: OPENAI_API_KEY not set in .env or environment.")

    return NootesConfig(
        watch_dir=Path(watch_dir_str).expanduser().resolve(),
        openai_api_key=api_key,
        github_repo=os.getenv("GITHUB_REPO"),
    )
