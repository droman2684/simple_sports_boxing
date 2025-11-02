# engine.py
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
import math, random

@dataclass
class Fighter:
    boxer_id: int
    name: str
    speed: int         # 0-100
    accuracy: int      # 0-100
    power: int         # 0-100
    defense: int       # 0-100
    stamina: int       # 0-100
    durability: int    # 0-100

# -------- Helpers --------

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

def _pct(x: int) -> float:
    # map 0..100 -> 0.0..1.0 (clamp)
    return max(0.0, min(1.0, x / 100.0))

def _score_round(landed_a: int, landed_b: int, kd_a: int, kd_b: int, judge_bias: float = 0.0) -> Tuple[int, int]:
    """
    Return (a_points, b_points) for one judge in a single round.
    judge_bias >0 leans toward A a tiny bit, <0 toward B.
    """
    margin = (landed_a - landed_b) + judge_bias
    if margin > 0.5:
        a, b = 10, 9
    elif margin < -0.5:
        a, b = 9, 10
    else:
        a = 10
        b = 10  # even round

    # Knockdowns modify scoring (10-8 typical, 10-7 for two)
    if kd_a >= 1 and a >= b:
        b = max(7, b - kd_a)
    if kd_b >= 1 and b >= a:
        a = max(7, a - kd_b)

    # If the loser scored a KD, keep losses reasonable
    if kd_a >= 1 and b > a:
        b = max(9, b)
    if kd_b >= 1 and a > b:
        a = max(9, a)

    return a, b

# -------- Engine Core --------

def simulate_fight(a: Fighter, b: Fighter, rounds: int = 12, seed: Optional[int] = None) -> Dict[str, Any]:
    """
    Simulate a boxing match between fighters a and b.
    Returns a dict with result, scorecards, totals, and play_by_play.
    """
    rng = random.Random(seed)

    # Derived modifiers (normalize 0..1)
    spd_a, spd_b = _pct(a.speed), _pct(b.speed)
    acc_a, acc_b = _pct(a.accuracy), _pct(b.accuracy)
    pow_a, pow_b = _pct(a.power), _pct(b.power)
    def_a, def_b = _pct(a.defense), _pct(b.defense)
    sta_a, sta_b = _pct(a.stamina), _pct(b.stamina)
    dur_a, dur_b = _pct(a.durability), _pct(b.durability)

    # State
    damage_a = 0.0  # accumulated damage TO A
    damage_b = 0.0  # accumulated damage TO B
    fatigue_a = 0.0
    fatigue_b = 0.0
    kd_total_a = 0  # knockdowns suffered BY A
    kd_total_b = 0

    judges = [[0, 0], [0, 0], [0, 0]]  # three judges total points [[A,B], ...]
    pbp: List[Dict[str, Any]] = []

    # KO/TKO thresholds tuned for realism (higher = harder to stop)
    ko_threshold_a = 220.0 * (1.0 - dur_a) + 160.0
    ko_threshold_b = 220.0 * (1.0 - dur_b) + 160.0

    # Per-round loop
    for rnd in range(1, rounds + 1):
        # Attempt count
