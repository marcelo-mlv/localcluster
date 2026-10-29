"""
Scenario configuration loading and resolution for the distributed processor.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from .config import DEFAULT_SCENARIO_CONFIG


def _builtin_qr_config() -> Dict[str, Any]:
    """Return the built-in Quick-Reaction scenario configuration dict."""
    return {
        "name": "Quick-Reaction",
        "description": "Blue fighter survival time vs Red radar longitude",
        "x_variable": {
            "name": "red_radar_longitude",
            "entity_selector": {"side": "red", "type_contains": "radar"},
            "field_path": "state.geo_pos.longitude",
            "frame_aggregation": "last",
            "scope": "per_experiment",
        },
        "y_variable": {
            "name": "blue_fighter_survival_time_frames",
            "entity_selector": {"side": "blue", "type_contains": "fighter"},
            "field_path": "frame",
            "frame_aggregation": "max",
            "scope": "per_entity",
        },
        "batch_aggregation": {
            "type": "pearson_correlation",
        },
    }


def load_scenario_config(config_path: str) -> Dict[str, Any]:
    """Load and return a scenario config from a YAML file."""
    if not _YAML_AVAILABLE:
        raise RuntimeError(
            "pyyaml is not installed. Add it to the Dockerfile or run `pip install pyyaml`."
        )
    with open(config_path, encoding="utf-8") as fh:
        return _yaml.safe_load(fh)


def resolve_scenario_config(cli_path: Optional[str]) -> Dict[str, Any]:
    """
    Resolve the scenario config to use, in priority order:
    1. CLI ``--scenario-config`` argument (if the file exists).
    2. ``DEFAULT_SCENARIO_CONFIG`` (if the file exists).
    3. Built-in QR defaults (fallback).
    """
    for path in filter(None, [cli_path, DEFAULT_SCENARIO_CONFIG]):
        if os.path.exists(path):
            try:
                cfg = load_scenario_config(path)
                print(f"INFO: Loaded scenario config from {path}", flush=True)
                return cfg
            except Exception as exc:
                print(f"WARNING: Failed to load scenario config {path}: {exc}", flush=True)

    print("INFO: Using built-in Quick-Reaction scenario defaults.", flush=True)
    return _builtin_qr_config()
