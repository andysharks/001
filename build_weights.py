"""Tunable weights for AI ship-building decisions."""

from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_JSON = Path(__file__).resolve().parent / "config" / "build_weights.default.json"
_ACTIVE_JSON = Path(__file__).resolve().parent / "config" / "build_weights.active.json"


DEFAULT_BUILD_WEIGHTS: dict[str, float] = {
    "bias": 0.0,
    "cheap_unit": 6.0,
    "expensive_unit": -4.0,
    "hull_hp": 3.5,
    "hull_damage": 8.0,
    "hull_range": 5.0,
    "movement": 8.0,
    "air_capacity": 2.0,
    "is_destroyer": 24.0,
    "is_light_destroyer": 18.0,
    "is_cruiser": 10.0,
    "is_heavy_cruiser": 12.0,
    "is_dreadnaught": 10.0,
    "is_carrier": 8.0,
    "is_super_star_destroyer": 14.0,
    "is_light_cruiser": 10.0,
    "is_hangar_fighter": 30.0,
    "is_hangar_bomber": 26.0,
    "need_destroyer_anchor": 70.0,
    "locked_non_destroyers": 22.0,
    "enemy_air_advantage": 20.0,
    "allied_air_deficit": 14.0,
    "carrier_capacity_need": 12.0,
    "bomber_vs_unguarded_base": 65.0,
    "enemy_base_pressure": 12.0,
    "friendly_base_threatened": 34.0,
    "tank_guard_needed": 42.0,
    "friendly_base_unguarded": 12.0,
    "anti_dread_light": 34.0,
    "anti_cruiser_carrier": 38.0,
    "need_frontline_hp": 10.0,
    "early_destroyer_expansion": 14.0,
    "early_mobile_expansion": 8.0,
    "scrap_float_penalty": -2.0,
}


def merge_build_weights(
    overlay: dict[str, float] | None,
    base: dict[str, float] | None = None,
) -> dict[str, float]:
    """Merge a partial build-weight overlay into defaults."""
    out = dict(base if base is not None else DEFAULT_BUILD_WEIGHTS)
    if overlay:
        for key, value in overlay.items():
            if isinstance(value, (int, float)) and key in out:
                out[key] = float(value)
    return out


def load_build_weights_file(path: str | Path | None) -> dict[str, float]:
    """Layered loads: builtin defaults -> default JSON -> active learned JSON -> optional path."""
    weights = merge_build_weights(None)
    if _DEFAULT_JSON.exists():
        blob = json.loads(_DEFAULT_JSON.read_text(encoding="utf-8"))
        overlay = blob.get("build_weights", blob) if isinstance(blob, dict) else {}
        if isinstance(overlay, dict):
            weights = merge_build_weights(
                {k: float(v) for k, v in overlay.items() if isinstance(v, (int, float))},
                base=weights,
            )
    if _ACTIVE_JSON.exists():
        blob = json.loads(_ACTIVE_JSON.read_text(encoding="utf-8"))
        overlay = blob.get("build_weights", blob) if isinstance(blob, dict) else {}
        if isinstance(overlay, dict):
            weights = merge_build_weights(
                {k: float(v) for k, v in overlay.items() if isinstance(v, (int, float))},
                base=weights,
            )
    if path:
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        overlay = blob.get("build_weights", blob) if isinstance(blob, dict) else {}
        if isinstance(overlay, dict):
            weights = merge_build_weights(
                {k: float(v) for k, v in overlay.items() if isinstance(v, (int, float))},
                base=weights,
            )
    return weights


def score_build_features(features: dict[str, float], weights: dict[str, float]) -> float:
    """Dot product restricted to known build feature keys."""
    return sum(weights.get(k, 0.0) * features.get(k, 0.0) for k in weights)
