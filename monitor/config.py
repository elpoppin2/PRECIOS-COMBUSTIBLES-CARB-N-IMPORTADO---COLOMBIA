from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
DATA_DIR = ROOT / "data"
HIST_PATH = DATA_DIR / "historico" / "series.csv"
MANUAL_DIR = DATA_DIR / "manual"
REPORTS_DIR = ROOT / "reports"


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
