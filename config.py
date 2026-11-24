from __future__ import annotations

import json
from pathlib import Path
from typing import Any

APP_NAME = "翻译悬浮窗"
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_config(cfg: dict[str, Any]) -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
