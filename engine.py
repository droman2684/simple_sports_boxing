# engine.py
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
import math, random

# --------------------------------------------------------------------
# Tuning knobs (safe defaults: fewer early KOs, more decisions)
# --------------------------------------------------------------------
TUNE = {
    # Knockdown probability components
    "KD_BASE":   0.0004,
    "KD_POW":    0.0010,
    "KD_STACK":  0.0005,   # scales with cumulative damage

    # One-punch KO probability components (gated by damage)
    "KO_BASE":   0.00002,
    "KO_POW":    0.00070,
    "KO_STACK":  0.00040,

    # Require some cumulative damage before KO can occur at all
    "MIN_DAMAGE_FOR_KO": 110.0,

    # After a KD, make immediate TKO less likely
    "TKO_AFTER_KD_MULT": 0.95,  # higher = harder to stop

    # Between-round TKO difficulty (base + jitter*rand)
    "BETWEEN_ROUNDS_TKO_MULT_BASE": 0.98,
    "BETWEEN_ROUNDS_TKO_MULT_JIT":  0.06,

    # KD bonus damage (capped lower than arcade)
    "KD_BONUS_MIN": 2.0,
    "KD_BONUS_PER_POW": 2.5,   # power is 0..1

    # Early-round reducer for KO chances (round index 0..11)
    "EARLY_KO_REDUCER": [0.35, 0.55, 0.75, 0.90, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],

    # Stamina-based between-round fatigue recovery
    "RECOVERY_BASE":    0.015,
    "RECOVERY_PER_STA": 0.035,
}

# --------------------------------------------------------------------
# Model
# --------------------------------------------------------------------
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

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

def _pct(x: int) -> float:
    # map 0..100 -> 0.0..1.0 (clamp)
    return max(0.0, min(1.0, x / 100.0))

def _score_round(landed_a: int, landed_b: int, kd_a: int, kd_b: int, judge_bias: float = 0.0) -> Tuple[int, int]:
    """
    Return (a_points, b_points) for one judge in a single round.
    judge_bias > 0 leans toward A a tiny bit, < 0 toward B.
    """
    margin = (landed_a - landed_b) + judge_bias
    if margin > 0.5:
        a, b = 10, 9
    elif margin < -0.5:
        a, b = 9, 10
    else:
        a, b = 10, 10  # even

    # Knockdowns modify scoring (10-8 typical; 10-7 if two KDs)
    if kd_a >= 1 and a >= b:
        b = max(7, b - kd_a)
    if kd_b >= 1 and b >= a:
        a = max(7, a - kd_b)

    # If the round winner was knocked down (rare), soften margin
    if kd_a >= 1 and b > a:
        b = max(9, b)
    if kd_b >= 1 and a > b:
        a = max(9, a)

    return a, b

# --------------------------------------------------------------------
# Engine Core
# --------------------------------------------------------------------
def simulate_fight(a: Fighter, b: Fighter, rounds: int = 12, seed: Optional[int] = None) -> Dict[str, Any]:
    """
    Simulate a boxing match between fighters a and b.
    Returns a dict with result, scorecards, totals, and play_by_play.
    """
    rng = random.Random(seed)

    # Normalize ratings to 0..1
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

    judges = [[0, 0], [0, 0], [0, 0]]  # three judges [ [A,B], ... ]
    pbp: List[Dict[str, Any]] = []

    # KO/TKO thresholds (keep fairly high; durability reduces threshold)
    # If you want even fewer stoppages overall, nudge the +300 up to +330.
    ko_threshold_a = 350.0 * (1.0 - dur_a) + 300.0
    ko_threshold_b = 350.0 * (1.0 - dur_b) + 300.0

    # Rounds
    for rnd in range(1, rounds + 1):
        # Attempt counts influenced by speed, stamina, and fatigue
        base_exchange = 48 + int(32 * (spd_a + spd_b) / 2)
        attempts_a = max(10, int(base_exchange * (0.50 + 0.5 * spd_a) * (0.65 + 0.35 * sta_a) * (1.0 - 0.35 * fatigue_a)))
        attempts_b = max(10, int(base_exchange * (0.50 + 0.5 * spd_b) * (0.65 + 0.35 * sta_b) * (1.0 - 0.35 * fatigue_b)))

        landed_a = 0
        landed_b = 0
        kd_a = 0
        kd_b = 0
        notes: List[str] = []

        total_attempts = attempts_a + attempts_b
        for _ in range(total_attempts):
            a_att_prob = (spd_a * (1.0 - fatigue_a) + sta_a * 0.5) / (
                (spd_a * (1.0 - fatigue_a) + sta_a * 0.5) +
                (spd_b * (1.0 - fatigue_b) + sta_b * 0.5) + 1e-9
            )
            attacker_is_a = rng.random() < a_att_prob

            if attacker_is_a:
                # A attacks
                hit_chance = _sigmoid(2.25 * ((acc_a - def_b) + 0.15 * (sta_a - fatigue_a) - 0.10 * (fatigue_b)))
                hit_chance = max(0.15, min(0.75, hit_chance))
                if rng.random() < hit_chance:
                    landed_a += 1
                    dmg = 3.0 + 9.0 * pow_a * (0.6 + 0.8 * rng.random()) - 2.0 * def_b
                    dmg *= (1.0 + 0.15 * (1.0 - fatigue_a)) * (0.95 + 0.10 * rng.random())
                    dmg = max(0.5, dmg)
                    damage_b += dmg

                    # KD check
                    kd_prob = (
                        TUNE["KD_BASE"]
                        + TUNE["KD_POW"] * pow_a
                        + TUNE["KD_STACK"] * max(0.0, (damage_b - 85.0) / 85.0)
                    )
                    if rng.random() < kd_prob:
                        kd_a += 1
                        kd_total_b += 1
                        notes.append(f"{a.name} scores a knockdown!")
                        damage_b += TUNE["KD_BONUS_MIN"] + TUNE["KD_BONUS_PER_POW"] * pow_a

                        # Post-KD TKO check (harder than default)
                        tko_mult = TUNE["TKO_AFTER_KD_MULT"] + 0.05 * rng.random()
                        if damage_b > ko_threshold_b * tko_mult:
                            return _result_tko(a, b, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

                    # One-punch KO (rare & gated)
                    if damage_b >= TUNE["MIN_DAMAGE_FOR_KO"]:
                        early = TUNE["EARLY_KO_REDUCER"][min(rnd - 1, 11)]
                        ko_prob = early * (
                            TUNE["KO_BASE"]
                            + TUNE["KO_POW"] * pow_a
                            + TUNE["KO_STACK"] * max(0.0, (damage_b - 120.0) / 80.0)
                        )
                        if rng.random() < ko_prob:
                            notes.append(f"{a.name} scores a knockout blow!")
                            return _result_ko(a, b, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

            else:
                # B attacks
                hit_chance = _sigmoid(2.25 * ((acc_b - def_a) + 0.15 * (sta_b - fatigue_b) - 0.10 * (fatigue_a)))
                hit_chance = max(0.15, min(0.75, hit_chance))
                if rng.random() < hit_chance:
                    landed_b += 1
                    dmg = 3.0 + 9.0 * pow_b * (0.6 + 0.8 * rng.random()) - 2.0 * def_a
                    dmg *= (1.0 + 0.15 * (1.0 - fatigue_b)) * (0.95 + 0.10 * rng.random())
                    dmg = max(0.5, dmg)
                    damage_a += dmg

                    # KD check
                    kd_prob = (
                        TUNE["KD_BASE"]
                        + TUNE["KD_POW"] * pow_b
                        + TUNE["KD_STACK"] * max(0.0, (damage_a - 85.0) / 85.0)
                    )
                    if rng.random() < kd_prob:
                        kd_b += 1
                        kd_total_a += 1
                        notes.append(f"{b.name} scores a knockdown!")
                        damage_a += TUNE["KD_BONUS_MIN"] + TUNE["KD_BONUS_PER_POW"] * pow_b

                        tko_mult = TUNE["TKO_AFTER_KD_MULT"] + 0.05 * rng.random()
                        if damage_a > ko_threshold_a * tko_mult:
                            return _result_tko(b, a, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

                    # One-punch KO (rare & gated)
                    if damage_a >= TUNE["MIN_DAMAGE_FOR_KO"]:
                        early = TUNE["EARLY_KO_REDUCER"][min(rnd - 1, 11)]
                        ko_prob = early * (
                            TUNE["KO_BASE"]
                            + TUNE["KO_POW"] * pow_b
                            + TUNE["KO_STACK"] * max(0.0, (damage_a - 120.0) / 80.0)
                        )
                        if rng.random() < ko_prob:
                            notes.append(f"{b.name} scores a knockout blow!")
                            return _result_ko(b, a, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

        # Between-round TKO checks (rarer)
        base = TUNE["BETWEEN_ROUNDS_TKO_MULT_BASE"]
        jit  = TUNE["BETWEEN_ROUNDS_TKO_MULT_JIT"]
        if damage_a > ko_threshold_a * (base + jit * rng.random()):
            notes.append(f"Corner stops it for {a.name}.")
            return _result_tko(b, a, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)
        if damage_b > ko_threshold_b * (base + jit * rng.random()):
            notes.append(f"Corner stops it for {b.name}.")
            return _result_tko(a, b, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

        # Judges score the round (three judges w/ tiny bias)
        for _ in range(3):
            bias = (rng.random() - 0.5) * 0.4
            a_pts, b_pts = _score_round(landed_a, landed_b, kd_a, kd_b, judge_bias=bias)
            judges[0][0] += a_pts
            judges[0][1] += b_pts
            # make them slightly different
            bias = (rng.random() - 0.5) * 0.4
            a_pts, b_pts = _score_round(landed_a, landed_b, kd_a, kd_b, judge_bias=bias)
            judges[1][0] += a_pts
            judges[1][1] += b_pts
            bias = (rng.random() - 0.5) * 0.4
            a_pts, b_pts = _score_round(landed_a, landed_b, kd_a, kd_b, judge_bias=bias)
            judges[2][0] += a_pts
            judges[2][1] += b_pts
            break  # scored once per round across 3 judges

        pbp.append({
            "round": rnd,
            "landed_a": landed_a,
            "landed_b": landed_b,
            "kd_a": kd_a,
            "kd_b": kd_b,
            "notes": notes,
        })

        # Between-round recovery (lets fights breathe)
        rec_a = TUNE["RECOVERY_BASE"] + TUNE["RECOVERY_PER_STA"] * sta_a
        rec_b = TUNE["RECOVERY_BASE"] + TUNE["RECOVERY_PER_STA"] * sta_b
        fatigue_a = max(0.0, fatigue_a - rec_a)
        fatigue_b = max(0.0, fatigue_b - rec_b)

    # Decision
    cards: List[str] = []
    a_cards = 0
    b_cards = 0
    for (ja, jb) in judges:
        cards.append(f"{int(ja)}-{int(jb)}")
        if ja > jb:
            a_cards += 1
        elif jb > ja:
            b_cards += 1

    if a_cards > b_cards:
        verdict = "Unanimous Decision" if a_cards == 3 else ("Split Decision" if b_cards == 1 else "Majority Decision")
        winner = {"boxer_id": a.boxer_id, "name": a.name}
        loser  = {"boxer_id": b.boxer_id, "name": b.name}
    elif b_cards > a_cards:
        verdict = "Unanimous Decision" if b_cards == 3 else ("Split Decision" if a_cards == 1 else "Majority Decision")
        winner = {"boxer_id": b.boxer_id, "name": b.name}
        loser  = {"boxer_id": a.boxer_id, "name": a.name}
    else:
        verdict = "Draw"
        winner = None
        loser = None

    return {
        "result": {"type": "Decision", "verdict": verdict, "cards": cards},
        "winner": winner,
        "loser": loser,
        "totals": {
            "damage_to_a": round(damage_a, 2),
            "damage_to_b": round(damage_b, 2),
            "kd_suffered_a": kd_total_a,
            "kd_suffered_b": kd_total_b,
            "fatigue_a": round(fatigue_a, 2),
            "fatigue_b": round(fatigue_b, 2),
        },
        "play_by_play": pbp,
    }

# --------------------------------------------------------------------
# Result builders
# --------------------------------------------------------------------
def _result_tko(winner: Fighter, loser: Fighter, rnd: int,
                pbp: List[Dict[str, Any]],
                landed_a: int, landed_b: int, kd_a: int, kd_b: int,
                judges, notes: List[str], rng: random.Random) -> Dict[str, Any]:
    pbp.append({
        "round": rnd,
        "stoppage": True,
        "notes": notes + [f"Referee stops the fight. {winner.name} wins by TKO."]
    })
    return {
        "result": {"type": "TKO", "round": rnd},
        "winner": {"boxer_id": winner.boxer_id, "name": winner.name},
        "loser":  {"boxer_id": loser.boxer_id, "name": loser.name},
        "play_by_play": pbp
    }

def _result_ko(winner: Fighter, loser: Fighter, rnd: int,
               pbp: List[Dict[str, Any]],
               landed_a: int, landed_b: int, kd_a: int, kd_b: int,
               judges, notes: List[str], rng: random.Random) -> Dict[str, Any]:
    pbp.append({
        "round": rnd,
        "stoppage": True,
        "notes": notes + [f"{winner.name} wins by KO!"]
    })
    return {
        "result": {"type": "KO", "round": rnd},
        "winner": {"boxer_id": winner.boxer_id, "name": winner.name},
        "loser":  {"boxer_id": loser.boxer_id, "name": loser.name},
        "play_by_play": pbp
    }
