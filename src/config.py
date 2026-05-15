from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import structlog
import yaml
from dotenv import load_dotenv

from src.schemas import Profile

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)
TEMPLATES_DIR = ROOT / "templates"
RUNS_DIR = ROOT / "runs"
PROMPTS_DIR = ROOT / "src" / "prompts"
PROFILE_PATH = ROOT / "profile.yaml"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
BROWSER_USE_HEADLESS = os.environ.get("BROWSER_USE_HEADLESS", "false").lower() == "true"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


def load_profile(path: Path = PROFILE_PATH) -> Profile:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Profile.model_validate(data)


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def new_run_dir(company: str, role: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = f"{ts}-{_slug(company)}-{_slug(role)}"
    run_dir = RUNS_DIR / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:50]


def get_logger(run_dir: Path | None = None) -> structlog.BoundLogger:
    processors = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(processors=processors)
    log = structlog.get_logger()
    if run_dir:
        log = log.bind(run=run_dir.name)
    return log
