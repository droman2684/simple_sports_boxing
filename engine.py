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

    # --- FIX 7: Increased TKO thresholds (again) ---
    ko_threshold_a = 350.0 * (1.0 - dur_a) + 300.0 # Was 320 / 280
    ko_threshold_b = 350.0 * (1.0 - dur_b) + 300.0 # Was 320 / 280

    # Per-round loop
    for rnd in range(1, rounds + 1):
        # Attempt counts influenced by speed, stamina, fatigue
        base_exchange = 48 + int(32 * (spd_a + spd_b) / 2)
        attempts_a = max(10, int(base_exchange * (0.50 + 0.5 * spd_a) * (0.65 + 0.35 * sta_a) * (1.0 - 0.35 * fatigue_a)))
        attempts_b = max(10, int(base_exchange * (0.50 + 0.5 * spd_b) * (0.65 + 0.35 * sta_b) * (1.0 - 0.35 * fatigue_b)))

        landed_a = 0
        landed_b = 0
        kd_a = 0
        kd_b = 0
        notes: List[str] = []

        # Each attempt: decide attacker by current freshness
        total_attempts = attempts_a + attempts_b
        for _ in range(total_attempts):
            a_att_prob = (spd_a * (1.0 - fatigue_a) + sta_a * 0.5) / (
                (spd_a * (1.0 - fatigue_a) + sta_a * 0.5) +
                (spd_b * (1.0 - fatigue_b) + sta_b * 0.5) + 1e-9
            )
            attacker_is_a = rng.random() < a_att_prob

            if attacker_is_a:
                # Hit probability factors: accuracy vs defense, freshness
                hit_chance = _sigmoid(2.25 * ((acc_a - def_b) + 0.15 * (sta_a - fatigue_a) - 0.10 * (fatigue_b)))
                hit_chance = max(0.15, min(0.75, hit_chance))
                if rng.random() < hit_chance:
                    landed_a += 1
                    
                    # --- FIX 8: Final Damage Formula (reduced power scaling) ---
                    dmg = 1.0 + 3.0 * pow_a * (0.6 + 0.8 * rng.random()) - 3.0 * def_b
                    dmg *= (1.0 + 0.15 * (1.0 - fatigue_a)) * (0.95 + 0.10 * rng.random())
                    dmg = max(0.5, dmg)
                    damage_b += dmg

                    # --- FIX 2: Reduced per-punch probabilities (from first fix) ---
                    kd_prob = 0.001 + 0.0015 * pow_a + 0.0008 * max(0.0, (damage_b - 75.0) / 75.0)
                    if rng.random() < kd_prob:
                        kd_a += 1
                        kd_total_b += 1
                        notes.append(f"{a.name} scores a knockdown!")
                        damage_b += 3 + 4 * pow_a

                        if damage_b > ko_threshold_b * (0.85 + 0.10 * rng.random()):
                            # --- BUG FIX: Pass 'rng' ---
                            return _result_tko(a, b, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

                    # --- FIX 2: Reduced per-punch probabilities (from first fix) ---
                    ko_prob = 0.0001 + 0.0015 * pow_a + 0.0008 * max(0.0, (damage_b - 90.0) / 60.0)
                    if rng.random() < ko_prob:
                        notes.append(f"{a.name} scores a knockout blow!")
                        # --- BUG FIX: Pass 'rng' ---
                        return _result_ko(a, b, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)
            else:
                hit_chance = _sigmoid(2.25 * ((acc_b - def_a) + 0.15 * (sta_b - fatigue_b) - 0.10 * (fatigue_a)))
                hit_chance = max(0.15, min(0.75, hit_chance))
                if rng.random() < hit_chance:
                    landed_b += 1

                    # --- FIX 8: Final Damage Formula (reduced power scaling) ---
                    dmg = 1.0 + 3.0 * pow_b * (0.6 + 0.8 * rng.random()) - 3.0 * def_a
                    dmg *= (1.0 + 0.15 * (1.0 - fatigue_b)) * (0.95 + 0.10 * rng.random())
                    dmg = max(0.5, dmg)
                    damage_a += dmg

                    # --- FIX 2: Reduced per-punch probabilities (from first fix) ---
                    kd_prob = 0.001 + 0.0015 * pow_b + 0.0008 * max(0.0, (damage_a - 75.0) / 75.0)
                    if rng.random() < kd_prob:
                        kd_b += 1
                        kd_total_a += 1
                        notes.append(f"{b.name} scores a knockdown!")
                        damage_a += 3 + 4 * pow_b
                        if damage_a > ko_threshold_a * (0.85 + 0.10 * rng.random()):
                            # --- BUG FIX: Pass 'rng' ---
                            return _result_tko(b, a, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

                    # --- FIX 2: Reduced per-punch probabilities (from first fix) ---
                    ko_prob = 0.0001 + 0.0015 * pow_b + 0.0008 * max(0.0, (damage_a - 90.0) / 60.0)
                    if rng.random() < ko_prob:
                        notes.append(f"{b.name} scores a knockout blow!")
                        # --- BUG FIX: Pass 'rng' ---
                        return _result_ko(b, a, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

        # Between-round TKO if someone took a beating
        if damage_a > ko_threshold_a * (0.95 + 0.10 * rng.random()):
            notes.append(f"Corner stops it for {a.name}.")
            # --- BUG FIX: Pass 'rng' ---
            return _result_tko(b, a, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)
        if damage_b > ko_threshold_b * (0.95 + 0.10 * rng.random()):
            notes.append(f"Corner stops it for {b.name}.")
            # --- BUG FIX: Pass 'rng' ---
            return _result_tko(a, b, rnd, pbp, landed_a, landed_b, kd_a, kd_b, judges, notes, rng)

        # --- NEW: Capture per-judge scores for this round ---
        round_score_cards: List[str] = []

        # Judges score the round (three judges with tiny noise)
        for j in range(3):
            bias = (rng.random() - 0.5) * 0.4  # small lean
            a_pts, b_pts = _score_round(landed_a, landed_b, kd_a, kd_b, judge_bias=bias)
            judges[j][0] += a_pts
            judges[j][1] += b_pts
            # --- NEW: Add this round's score string to the list ---
            round_score_cards.append(f"{int(a_pts)}-{int(b_pts)}")

        pbp.append({
            "round": rnd,
            "landed_a": landed_a,
            "landed_b": landed_b,
            "kd_a": kd_a,
            "kd_b": kd_b,
            "notes": notes,
            "judge_scores": round_score_cards  # --- ADDED: "judge_scores" key ---
        })

        # --- FIX 4: Increased Fatigue (from second fix) ---
        total_landed = max(1, landed_a + landed_b)
        fatigue_a += 0.055 + 0.025 * (landed_b / total_landed)
        fatigue_b += 0.055 + 0.025 * (landed_a / total_landed)
        
        # --- FIX 9: (NEW) Fatigue Recovery between rounds based on stamina ---
        fatigue_recovery_a = 0.01 + 0.03 * sta_a
        fatigue_recovery_b = 0.01 + 0.03 * sta_b
        
        fatigue_a = max(0.0, fatigue_a - fatigue_recovery_a)
        fatigue_b = max(0.0, fatigue_b - fatigue_recovery_b)

        # Clamp fatigue just in case
        fatigue_a = min(0.9, fatigue_a)
        fatigue_b = min(0.9, fatigue_b)

    # If we get here, it’s a decision
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
        loser = {"boxer_id": b.boxer_id, "name": b.name}
    elif b_cards > a_cards:
        verdict = "Unanimous Decision" if b_cards == 3 else ("Split Decision" if a_cards == 1 else "Majority Decision")
        winner = {"boxer_id": b.boxer_id, "name": b.name}
        loser = {"boxer_id": a.boxer_id, "name": a.name}
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

# -------- Result builders --------

# --- BUG FIX: Added 'rng' to function definition ---
def _result_tko(winner: Fighter, loser: Fighter, rnd: int,
                pbp: List[Dict[str, Any]],
                landed_a: int, landed_b: int, kd_a: int, kd_b: int,
                judges, notes: List[str], rng: random.Random) -> Dict[str, Any]:
    
    # --- ADDITION: Score the final, interrupted round ---
    round_score_cards: List[str] = []
    for j in range(3):
        # --- BUG FIX: Use the passed 'rng' object ---
        bias = (rng.random() - 0.5) * 0.4
        a_pts, b_pts = _score_round(landed_a, landed_b, kd_a, kd_b, judge_bias=bias)
        round_score_cards.append(f"{int(a_pts)}-{int(b_pts)}")

    pbp.append({
        "round": rnd,
        "stoppage": True,
        "landed_a": landed_a,
        "landed_b": landed_b,
        "kd_a": kd_a,
        "kd_b": kd_b,
        "notes": notes + [f"Referee stops the fight. {winner.name} wins by TKO."],
        "judge_scores": round_score_cards
    })
    return {
        "result": {"type": "TKO", "round": rnd},
        "winner": {"boxer_id": winner.boxer_id, "name": winner.name},
        "loser": {"boxer_id": loser.boxer_id, "name": loser.name},
        "play_by_play": pbp
    }

# --- BUG FIX: Added 'rng' to function definition ---
def _result_ko(winner: Fighter, loser: Fighter, rnd: int,
               pbp: List[Dict[str, Any]],
               landed_a: int, landed_b: int, kd_a: int, kd_b: int,
               judges, notes: List[str], rng: random.Random) -> Dict[str, Any]:

    # --- ADDITION: Score the final, interrupted round ---
    round_score_cards: List[str] = []
    for j in range(3):
        # --- BUG FIX: Use the passed 'rng' object ---
        bias = (rng.random() - 0.5) * 0.4
        a_pts, b_pts = _score_round(landed_a, landed_b, kd_a, kd_b, judge_bias=bias)
        round_score_cards.append(f"{int(a_pts)}-{int(b_pts)}")
        
    pbp.append({
        "round": rnd,
        "stoppage": True,
        "landed_a": landed_a,
        "landed_b": landed_b,
        "kd_a": kd_a,
        "kd_b": kd_b,
        "notes": notes + [f"{winner.name} wins by KO!"],
        "judge_scores": round_score_cards
    })
    return {
        "result": {"type": "KO", "round": rnd},
        "winner": {"boxer_id": winner.boxer_id, "name": winner.name},
        "loser": {"boxer_id": loser.boxer_id, "name": loser.name},
        "play_by_play": pbp
    }