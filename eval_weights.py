"""Evaluation weights multiplied against raw feature-vector components produced in game_logic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT_JSON = Path(__file__).resolve().parent / "config" / "eval_weights.default.json"

# Canonical keys consumed by evaluate_board / compute_evaluation_features.
# Defaults reproduce the pre-refactor heuristic when multiplied by extracted raw features.
DEFAULT_EVAL_WEIGHTS: dict[str, float] = {
    "mobility_lock": 1.0,
    "fleet_material_core": 1.0,
    "charge_pressure": 1.0,
    "dread_kiting": 1.0,
    "dread_light_threat": 1.0,
    "early_planet_pressure": 1.0,
    "early_base_on_planet": 1.0,
    "center_manhattan_units": 0.5,
    "core_band_occupancy": 1.8,
    "threat_balance": 0.5,
    "focus_fire_kill": 1.0,
    "focus_fire_base": 1.0,
    "base_guard": 1.0,
    "base_unguarded": 1.0,
    "base_hyper_threat": 1.0,
    "base_defender_hp_term": 1.0,
    "aircraft_dominance": 0.8,
    "cqb_adjacent_pressure": 1.0,
    "cqb_local_air": 1.0,
    "cqb_melee_leverage": 1.0,
    "cqb_initiative": 1.0,
}


def merge_eval_weights(overlay: dict[str, float] | None, base: dict[str, float] | None = None) -> dict[str, float]:
    """Merge partial ``overlay`` into ``base`` or into DEFAULT_EVAL_WEIGHTS."""
    out = dict(base if base is not None else DEFAULT_EVAL_WEIGHTS)
    if overlay:
        for k, v in overlay.items():
            if isinstance(v, (int, float)) and k in out:
                out[k] = float(v)
    return out


def load_eval_weights_file(path: str | Path | None) -> dict[str, float]:
    """Layered loads: builtin defaults → ``config/eval_weights.default.json`` → optional CLI path."""
    w = merge_eval_weights(None)
    if _DEFAULT_JSON.exists():
        blob = json.loads(_DEFAULT_JSON.read_text(encoding="utf-8"))
        ov = blob.get("eval_weights", blob) if isinstance(blob, dict) else {}
        if isinstance(ov, dict):
            w = merge_eval_weights({k: float(v) for k, v in ov.items() if isinstance(v, (int, float))}, base=w)
    if path:
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        ov = blob.get("eval_weights", blob) if isinstance(blob, dict) else {}
        if isinstance(ov, dict):
            w = merge_eval_weights({k: float(v) for k, v in ov.items() if isinstance(v, (int, float))}, base=w)
    return w


def score_from_features(features: dict[str, float], weights: dict[str, float]) -> float:
    """Dot product restricted to canonical keys."""
    return sum(weights.get(k, 0.0) * features.get(k, 0.0) for k in weights)
