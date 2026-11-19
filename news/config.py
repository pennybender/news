import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("NEWS_CONFIG", ROOT / "feeds.toml"))

DEFAULT_SETTINGS = {
    "keep_days": 7,
    "front_page_size": 7,
    "max_per_section": 2,
    "dedupe_threshold": 0.6,
}


def load_config():
    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    cfg["settings"] = {**DEFAULT_SETTINGS, **cfg.get("settings", {})}
    section_ids = {s["id"] for s in cfg.get("sections", [])}
    for src in cfg.get("sources", []):
        src.setdefault("weight", 1.0)
        src.setdefault("long_read", False)
        src.setdefault("paywalled", False)
        src.setdefault("include", [])
        src.setdefault("max_items", 30)
        if src["section"] not in section_ids:
            raise ValueError(f"Source {src['name']!r} uses unknown section {src['section']!r}")
    return cfg
