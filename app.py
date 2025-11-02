# app.py
import os
from pathlib import Path

from flask import (
    Flask, render_template, request, abort,
    redirect, url_for, flash, jsonify, send_from_directory
)
from flask_cors import CORS
from dotenv import load_dotenv

from engine import Fighter, simulate_fight


# Central DB helpers (must expose: get_conn, fetch_one, fetch_all, execute)
import db

# -----------------------------------------------------------------------------
# App Setup (absolute paths = bulletproof static + templates)
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv()

app = Flask(
    __name__,
    static_folder=str(BASE_DIR / "static"),
    static_url_path="/static",
    template_folder=str(BASE_DIR / "templates"),
)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-later")

# Optional CORS (kept per your snippet). If you don't need it, remove these 2 lines.
CORS(app, resources={r"/*": {
    "origins": ["https://simplesportssim.com", "https://www.simplesportssim.com"]
}})

# In debug: kill static caching so CSS changes show immediately
if app.debug or os.getenv("FLASK_ENV") == "development":
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["TEMPLATES_AUTO_RELOAD"] = True

# Cache-busting helper you can use from templates: {{ asset('boxing.css') }}
@app.context_processor
def _inject_asset_helper():
    def asset(filename: str):
        try:
            fp = BASE_DIR / "static" / filename
            v = int(fp.stat().st_mtime)
        except Exception:
            v = 1
        return url_for("static", filename=filename, v=v)
    return {"asset": asset}

# -----------------------------------------------------------------------------
# DASHBOARD
# -----------------------------------------------------------------------------
@app.get("/")
def dashboard():
    classes = db.fetch_one("SELECT COUNT(*) AS count FROM boxing.weight_class")["count"]
    titles  = db.fetch_one("SELECT COUNT(*) AS count FROM boxing.title")["count"]
    boxers  = db.fetch_one("SELECT COUNT(*) AS count FROM boxing.boxer")["count"]
    cards   = db.fetch_one("SELECT COUNT(*) AS count FROM boxing.boxing_card")["count"]

    champions = db.fetch_all("""
        SELECT title_name, weight_class, body, boxer_id, first_name, last_name, start_date
        FROM boxing.v_current_champions
        ORDER BY weight_class, body
    """)

    recent = db.fetch_all("SELECT * FROM boxing.v_recent_bouts")

    return render_template(
        "dashboard.html",
        classes=classes, titles=titles, boxers=boxers, cards=cards,
        champions=champions, recent=recent
    )

# -----------------------------------------------------------------------------
# BOXERS
# -----------------------------------------------------------------------------
@app.get("/boxers")
def boxers():
    q = request.args.get("q", "").strip()
    sort = (request.args.get("sort") or "last_name").lower()
    direction = (request.args.get("dir") or "asc").lower()

    SORT_MAP = {
        "last_name": "b.last_name",
        "first_name": "b.first_name",
        "weight_class": "wc.name",
        "stable": "s.name",
        "wins": "COALESCE(r.wins,0)",
        "losses": "COALESCE(r.losses,0)",
        "draws": "COALESCE(r.draws,0)",
        "ko_wins": "COALESCE(r.ko_wins,0)",
    }
    sort_expr = SORT_MAP.get(sort, "b.last_name")
    dir_sql = "DESC" if direction == "desc" else "ASC"

    base_sql = """
      SELECT b.boxer_id, b.first_name, b.last_name,
             wc.name AS weight_class,
             s.stable_id, s.name AS stable_name,
             COALESCE(r.wins,0) AS wins, COALESCE(r.losses,0) AS losses,
             COALESCE(r.draws,0) AS draws, COALESCE(r.ko_wins,0) AS ko_wins
      FROM boxing.boxer b
      JOIN boxing.weight_class wc ON wc.weight_class_id = b.weight_class_id
      LEFT JOIN boxing.stable s ON s.stable_id = b.stable_id
      LEFT JOIN boxing.v_boxer_records r ON r.boxer_id = b.boxer_id
    """

    params, where = [], ""
    if q:
        where = """
            WHERE LOWER(b.first_name) LIKE %s
               OR LOWER(b.last_name)  LIKE %s
               OR LOWER(s.name)       LIKE %s
        """
        like = f"%{q.lower()}%"
        params = [like, like, like]

    order_by = f" ORDER BY {sort_expr} {dir_sql}, b.last_name ASC, b.first_name ASC, b.boxer_id ASC "
    sql = base_sql + where + order_by + " LIMIT 200"
    rows = db.fetch_all(sql, params)

    return render_template("boxers.html", rows=rows, q=q, sort=sort, direction=direction)

# NEW BOXER FORM
@app.get("/boxers/new")
def boxer_new():
    wcs = db.fetch_all("""
        SELECT weight_class_id, name
        FROM boxing.weight_class
        ORDER BY display_order, name
    """)
    stables = db.fetch_all("""
        SELECT stable_id, name, is_user_controlled
        FROM boxing.stable
        ORDER BY name
    """)
    default_stable = next((s for s in stables if s["is_user_controlled"]), None)
    form = {"stable_id": str(default_stable["stable_id"]) if default_stable else ""}
    return render_template("boxer_new.html", wcs=wcs, stables=stables, errors={}, form=form)

# CREATE BOXER
@app.post("/boxers/new")
def boxer_create():
    form = {
        "first_name": (request.form.get("first_name") or "").strip(),
        "last_name": (request.form.get("last_name") or "").strip(),
        "weight_class_id": request.form.get("weight_class_id"),
        "stable_id": request.form.get("stable_id"),
        "speed": request.form.get("speed"),
        "accuracy": request.form.get("accuracy"),
        "power": request.form.get("power"),
        "defense": request.form.get("defense"),
        "stamina": request.form.get("stamina"),
        "durability": request.form.get("durability"),
    }

    # Validation
    errors = {}
    if not form["first_name"]: errors["first_name"] = "Required"
    if not form["last_name"]:  errors["last_name"]  = "Required"
    if not form["weight_class_id"]: errors["weight_class_id"] = "Choose a weight class"
    if not form["stable_id"]:       errors["stable_id"]       = "Choose a stable"

    def valid_rating(v):
        try:
            x = int(v); return 0 <= x <= 100
        except: return False

    for k in ("speed","accuracy","power","defense","stamina","durability"):
        if not valid_rating(form[k]):
            errors[k] = "Enter 0–100"

    if errors:
        wcs = db.fetch_all("SELECT weight_class_id, name FROM boxing.weight_class ORDER BY name")
        stables = db.fetch_all("SELECT stable_id, name, is_user_controlled FROM boxing.stable ORDER BY name")
        return render_template("boxer_new.html", wcs=wcs, stables=stables, errors=errors, form=form), 400

    # Insert boxer
    boxer_row = db.fetch_one("""
        INSERT INTO boxing.boxer (first_name, last_name, weight_class_id, stable_id)
        VALUES (%s, %s, %s, %s)
        RETURNING boxer_id
    """, [form["first_name"], form["last_name"], form["weight_class_id"], form["stable_id"]])
    boxer_id = boxer_row["boxer_id"]

    # Insert ratings
    db.execute("""
        INSERT INTO boxing.boxer_ratings
          (boxer_id, speed, accuracy, power, defense, stamina, durability)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (boxer_id) DO UPDATE SET
          speed=EXCLUDED.speed,
          accuracy=EXCLUDED.accuracy,
          power=EXCLUDED.power,
          defense=EXCLUDED.defense,
          stamina=EXCLUDED.stamina,
          durability=EXCLUDED.durability
    """, [
        boxer_id,
        int(form["speed"]), int(form["accuracy"]), int(form["power"]),
        int(form["defense"]), int(form["stamina"]), int(form["durability"])
    ])

    flash(f"Added {form['first_name']} {form['last_name']}")
    return redirect(url_for("boxers"))

# -----------------------------------------------------------------------------
# CARDS
# -----------------------------------------------------------------------------
@app.get("/cards")
def cards():
    sort = (request.args.get("sort") or "event_date").lower()
    direction = (request.args.get("dir") or "desc").lower()

    SORT_MAP = {
        "event_date": "event_date",
        "event_name": "event_name",
        "city": "city",
        "country": "country",
        "bout_count": "bout_count",
    }
    sort_expr = SORT_MAP.get(sort, "event_date")
    dir_sql = "DESC" if direction == "desc" else "ASC"

    rows = db.fetch_all(f"""
        SELECT * FROM boxing.v_cards_summary
        ORDER BY {sort_expr} {dir_sql}, card_id DESC
    """)
    return render_template("cards.html", cards=rows, sort=sort, direction=direction)

@app.get("/cards/<int:card_id>")
def card_detail(card_id: int):
    card = db.fetch_one("SELECT * FROM boxing.v_cards_summary WHERE card_id = %s", [card_id])
    if not card:
        abort(404)

    bouts = db.fetch_all("""
      SELECT
        bo.bout_id, bo.bout_order, bo.main_event,
        wc.name AS weight_class, t.title_name,
        MAX(bx.first_name || ' ' || bx.last_name) FILTER (WHERE bp.corner = 'A') AS fighter_a,
        MAX(bx.first_name || ' ' || bx.last_name) FILTER (WHERE bp.corner = 'B') AS fighter_b,
        MAX(bx.first_name || ' ' || bx.last_name) FILTER (WHERE bp.result = 'win') AS winner,
        MAX(bp.method::text)                        FILTER (WHERE bp.result = 'win') AS method,
        MAX(bp.round_ended)                         FILTER (WHERE bp.result = 'win') AS round
      FROM boxing.bout bo
      JOIN boxing.weight_class     wc ON wc.weight_class_id = bo.weight_class_id
      LEFT JOIN boxing.title        t ON t.title_id = bo.title_id
      JOIN boxing.bout_participant bp ON bp.bout_id = bo.bout_id
      JOIN boxing.boxer            bx ON bx.boxer_id = bp.boxer_id
      WHERE bo.card_id = %s
      GROUP BY bo.bout_id, bo.bout_order, bo.main_event, wc.name, t.title_name
      ORDER BY bo.bout_order
    """, [card_id])

    return render_template("card_detail.html", card=card, bouts=bouts)

# -----------------------------------------------------------------------------
# STABLES
# -----------------------------------------------------------------------------
@app.get("/stables")
def stables():
    rows = db.fetch_all("""
        SELECT
            stable_id,
            name,
            founded_date,
            hq_city,
            is_user_controlled
        FROM boxing.stable
        ORDER BY name;
    """)
    return render_template("stables.html", stables=rows)

@app.get("/stables/<int:stable_id>")
def stable_detail(stable_id: int):
    stable = db.fetch_one("""
        SELECT
            stable_id,
            name,
            founded_date,
            hq_city,
            is_user_controlled,
            created_at
        FROM boxing.stable
        WHERE stable_id = %s;
    """, [stable_id])

    if not stable:
        abort(404)

    roster = db.fetch_all("""
        SELECT
            b.boxer_id,
            b.first_name,
            b.last_name,
            wc.name AS weight_class,
            COALESCE(r.wins,0)    AS wins,
            COALESCE(r.losses,0)  AS losses,
            COALESCE(r.draws,0)   AS draws,
            COALESCE(r.ko_wins,0) AS ko_wins
        FROM boxing.boxer b
        JOIN boxing.weight_class wc
            ON wc.weight_class_id = b.weight_class_id
        LEFT JOIN boxing.v_boxer_records r
            ON r.boxer_id = b.boxer_id
        WHERE b.stable_id = %s
        ORDER BY b.last_name, b.first_name;
    """, [stable_id])

    return render_template("stable_detail.html", stable=stable, roster=roster)

@app.get("/stables/new")
def new_stable():
    return render_template("new_stable.html")

@app.post("/stables")
def create_stable():
    name = (request.form.get("name") or "").strip()
    founded_date = request.form.get("founded_date") or None
    hq_city = request.form.get("hq_city") or None
    is_user_controlled = bool(request.form.get("is_user_controlled"))

    if not name:
        flash("Stable name is required.", "error")
        return redirect(url_for("new_stable"))

    db.execute("""
        INSERT INTO boxing.stable (name, founded_date, is_user_controlled, hq_city)
        VALUES (%s, %s, %s, %s);
    """, (name, founded_date, is_user_controlled, hq_city))

    flash(f'Stable "{name}" created.', "success")
    return redirect(url_for("stables"))

# --- FIGHT SIMULATION (JSON) ---
from engine import Fighter, simulate_fight

@app.post("/sim/fight")
def sim_fight():
    """
    POST JSON:
    {
      "boxer_a_id": 1,
      "boxer_b_id": 2,
      "rounds": 12,
      "seed": 42   # optional for reproducibility
    }
    """
    data = request.get_json(force=True) or {}
    a_id = int(data.get("boxer_a_id"))
    b_id = int(data.get("boxer_b_id"))
    rounds = int(data.get("rounds", 12))
    seed = data.get("seed")

    # Fetch fighters + ratings from DB
    row_a = db.fetch_one("""
        SELECT bx.boxer_id,
               bx.first_name || ' ' || bx.last_name AS name,
               r.speed, r.accuracy, r.power, r.defense, r.stamina, r.durability
        FROM boxing.boxer bx
        LEFT JOIN boxing.boxer_ratings r ON r.boxer_id = bx.boxer_id
        WHERE bx.boxer_id = %s
    """, [a_id])

    row_b = db.fetch_one("""
        SELECT bx.boxer_id,
               bx.first_name || ' ' || bx.last_name AS name,
               r.speed, r.accuracy, r.power, r.defense, r.stamina, r.durability
        FROM boxing.boxer bx
        LEFT JOIN boxing.boxer_ratings r ON r.boxer_id = bx.boxer_id
        WHERE bx.boxer_id = %s
    """, [b_id])

    if not row_a or not row_b:
        abort(400, "Invalid boxer ids")

    def to_int(x, default=50):
        try: return int(x)
        except: return default

    A = Fighter(
        boxer_id=row_a["boxer_id"], name=row_a["name"],
        speed=to_int(row_a.get("speed", 50)),
        accuracy=to_int(row_a.get("accuracy", 50)),
        power=to_int(row_a.get("power", 50)),
        defense=to_int(row_a.get("defense", 50)),
        stamina=to_int(row_a.get("stamina", 50)),
        durability=to_int(row_a.get("durability", 50)),
    )
    B = Fighter(
        boxer_id=row_b["boxer_id"], name=row_b["name"],
        speed=to_int(row_b.get("speed", 50)),
        accuracy=to_int(row_b.get("accuracy", 50)),
        power=to_int(row_b.get("power", 50)),
        defense=to_int(row_b.get("defense", 50)),
        stamina=to_int(row_b.get("stamina", 50)),
        durability=to_int(row_b.get("durability", 50)),
    )

    result = simulate_fight(A, B, rounds=rounds, seed=seed)
    return result, 200

# --- EXHIBITIONS: NEW (form to pick fighters) ---
@app.get("/exhibitions/new")
def exhibition_new():
    boxers = db.fetch_all("""
        SELECT
          b.boxer_id,
          (b.first_name || ' ' || b.last_name) AS name,
          wc.name AS weight_class
        FROM boxing.boxer b
        JOIN boxing.weight_class wc ON wc.weight_class_id = b.weight_class_id
        ORDER BY b.last_name, b.first_name
    """)
    return render_template("exhibition_new.html", boxers=boxers)


# --- EXHIBITIONS: SIMULATE (POST -> runs engine, shows result) ---
@app.post("/exhibitions/simulate")
def exhibition_simulate():
    a_id = int(request.form.get("boxer_a_id"))
    b_id = int(request.form.get("boxer_b_id"))
    rounds = int(request.form.get("rounds", 12))
    seed = request.form.get("seed")
    seed = int(seed) if seed not in (None, "",) else None

    if a_id == b_id:
        flash("Pick two different fighters.", "error")
        return redirect(url_for("exhibition_new"))

    # Fetch both fighters + ratings
    row_a = db.fetch_one("""
        SELECT bx.boxer_id,
               bx.first_name || ' ' || bx.last_name AS name,
               COALESCE(r.speed,50) AS speed,
               COALESCE(r.accuracy,50) AS accuracy,
               COALESCE(r.power,50) AS power,
               COALESCE(r.defense,50) AS defense,
               COALESCE(r.stamina,50) AS stamina,
               COALESCE(r.durability,50) AS durability
        FROM boxing.boxer bx
        LEFT JOIN boxing.boxer_ratings r ON r.boxer_id = bx.boxer_id
        WHERE bx.boxer_id = %s
    """, [a_id])

    row_b = db.fetch_one("""
        SELECT bx.boxer_id,
               bx.first_name || ' ' || bx.last_name AS name,
               COALESCE(r.speed,50) AS speed,
               COALESCE(r.accuracy,50) AS accuracy,
               COALESCE(r.power,50) AS power,
               COALESCE(r.defense,50) AS defense,
               COALESCE(r.stamina,50) AS stamina,
               COALESCE(r.durability,50) AS durability
        FROM boxing.boxer bx
        LEFT JOIN boxing.boxer_ratings r ON r.boxer_id = bx.boxer_id
        WHERE bx.boxer_id = %s
    """, [b_id])

    if not row_a or not row_b:
        flash("Invalid fighter selection.", "error")
        return redirect(url_for("exhibition_new"))

    A = Fighter(
        boxer_id=row_a["boxer_id"], name=row_a["name"],
        speed=int(row_a["speed"]), accuracy=int(row_a["accuracy"]),
        power=int(row_a["power"]), defense=int(row_a["defense"]),
        stamina=int(row_a["stamina"]), durability=int(row_a["durability"])
    )
    B = Fighter(
        boxer_id=row_b["boxer_id"], name=row_b["name"],
        speed=int(row_b["speed"]), accuracy=int(row_b["accuracy"]),
        power=int(row_b["power"]), defense=int(row_b["defense"]),
        stamina=int(row_b["stamina"]), durability=int(row_b["durability"])
    )

    sim = simulate_fight(A, B, rounds=rounds, seed=seed)

    # Pass data to a result page
    return render_template(
        "exhibition_result.html",
        a=A, b=B, rounds=rounds, seed=seed, sim=sim
    )



# -----------------------------------------------------------------------------
# Health / Static Debug (remove after verifying)
# -----------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            return {"status": "ok"}, 200
    except Exception as e:
        return {"status": "error", "detail": str(e)}, 500

@app.get("/_debug/static")
def _debug_static():
    folder = app.static_folder
    exists = os.path.isdir(folder)
    try:
        files = sorted(os.listdir(folder)) if exists else []
    except Exception as e:
        files = [f"<error listing: {e}>"]
    return jsonify({"static_folder": folder, "exists": exists, "files": files})

@app.get("/_debug/static/<path:name>")
def _debug_static_file(name):
    return send_from_directory(app.static_folder, name)

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(
        debug=True,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080"))
    )
