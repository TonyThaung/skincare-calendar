"""Simple Skincare Routine Calendar — Streamlit app with browser-persistent state.

State (completed AM/PM and shaving days) lives in the user's browser via
localStorage, so each visitor keeps their own progress across sessions —
even on Streamlit Community Cloud where the server filesystem is ephemeral.

Run locally:
    streamlit run app.py
"""
from __future__ import annotations

import base64
import calendar
import html
import json
import zlib
from datetime import date, timedelta

import streamlit as st
import streamlit.components.v1 as components

# Back-compat shim so existing function signatures still type-check.
# Real persistence now flows through the URL query param + localStorage
# bootstrap (see persist() / hydrate() below).
class LocalStorage:  # noqa: N801 - kept for signature compatibility
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
YEAR = 2026
START_DATE = date(2026, 4, 26)
END_DATE = date(2026, 12, 31)

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAMES_SHORT = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# Restricted 6-colour palette — black, white, yellow, green, blue, red.
# Each pill = (tint, ink, accent).
# Slot names kept for back-compat with routine_for().
YELLOW_TINT, YELLOW_INK, YELLOW = "#fef7d6", "#6b4f00", "#f5c518"
GREEN_TINT,  GREEN_INK,  GREEN  = "#d4f4dd", "#14532d", "#16a34a"
BLUE_TINT,   BLUE_INK,   BLUE   = "#dbe7ff", "#1e3a8a", "#2563eb"
RED_TINT,    RED_INK,    RED    = "#fde0e0", "#7f1d1d", "#dc2626"
GREY_TINT,   INK_BLACK,  MUTED  = "#f3f4f6", "#111111", "#6b7280"

PILL_COLORS = {
    "purple": (BLUE_TINT,   BLUE_INK,   BLUE),    # Retinal -> blue
    "blue":   (YELLOW_TINT, YELLOW_INK, YELLOW),  # Optional Toner -> yellow
    "green":  (GREEN_TINT,  GREEN_INK,  GREEN),   # Azelaic -> green
    "pink":   (RED_TINT,    RED_INK,    RED),     # Anua -> red
    "orange": (YELLOW_TINT, YELLOW_INK, YELLOW),  # Choose One -> yellow
    "grey":   (GREY_TINT,   INK_BLACK,  MUTED),   # Recovery -> grey/black
    "teal":   (GREEN_TINT,  GREEN_INK,  GREEN),   # Shaving -> green
}

ROUTINE_LEGEND = [
    ("purple", "Retinal", "MON · FRI", "Anti-ageing & texture", "Medik8 Crystal Retinal 6 · 2×/wk"),
    ("green", "Azelaic Acid", "WED · SUN", "Acne, redness & PIH", "Cos De BAHA 10% · 2×/wk"),
    ("pink", "Anua", "THU", "Pigmentation & tone", "Niacinamide + TXA · 1×/wk"),
    ("grey", "Recovery", "TUE · SAT", "Barrier repair, no actives", "Centella + Vanicream"),
    ("blue", "PHA (opt-in)", "SAT only if calm", "Gentle exfoliation, optional", "SKIN1004 toner · 0–1×/wk"),
]

PRODUCTS = [
    "Dr. Althea Gentle Vitamin C",
    "Purito Centella",
    "COSRX Snail Mucin",
    "Vanicream Ceramide Moisturiser",
    "Medik8 Retinal 6",
    "SKIN1004 Toner",
    "Cos De BAHA Azelaic Acid 10%",
    "Anua Niacinamide 10% + TXA 4%",
    "Beauty of Joseon Aqua Fresh SPF",
]

LS_DONE_KEY = "skincare_done_v2"
LS_SHAVE_KEY = "skincare_shave_days_v1"
LS_INTRO_KEY = "skincare_intro_seen_v1"
LS_CELEBRATED_KEY = "skincare_celebrated_streak_v1"
LS_OUTDOOR_KEY = "skincare_outdoor_days_v1"
LS_BREAKOUT_KEY = "skincare_breakout_week_v1"
LS_PATCH_KEY = "skincare_patch_test_v1"

STREAK_MILESTONES = (3, 7, 14, 30, 60, 100)

# Banish Kit 3.0 microneedling defaults
BANISH_DEFAULT_RECOVERY_DAYS = 2
BANISH_DEFAULT_CADENCE = "biweekly"  # weekly | biweekly | monthly
BANISH_DEFAULT_SERUM = "althea"      # althea | banish | other-gentle | l-aa | none
BANISH_HEAD_LIFETIME_SESSIONS = 4    # plan calls for swap every 4 sessions


# ---------------------------------------------------------------------------
# Banish helpers
# ---------------------------------------------------------------------------
def is_banish_day(d: date, banish_days: dict) -> bool:
    return bool((banish_days or {}).get(d.isoformat()))


def banish_recovery_offset(d: date, banish_days: dict, recovery_days: int = BANISH_DEFAULT_RECOVERY_DAYS) -> int:
    """Return 0 if `d` is not in a recovery window, else the offset (1, 2, ...)
    measured from the most recent banish session date that precedes `d`."""
    if not banish_days or recovery_days <= 0:
        return 0
    for offset in range(1, recovery_days + 1):
        check = (d - timedelta(days=offset)).isoformat()
        if banish_days.get(check):
            return offset
    return 0


def _banish_serum_step(serum_choice: str) -> str | None:
    """Returns the PM serum step for a Banish-day, or None to skip the step."""
    choice = (serum_choice or "").lower()
    if choice == "althea":
        return "Apply Dr. Althea Vitamin C Boosting Serum (2\u20133 drops, gentle press \u2014 do not rub)"
    if choice == "banish":
        return "Apply Banish Vitamin C Serum (2\u20133 drops, gentle press \u2014 do not rub)"
    if choice == "other-gentle":
        return "Apply your gentle vitamin C derivative serum (2\u20133 drops, gentle press)"
    if choice == "l-aa":
        return "SKIP vitamin C tonight \u2014 L-ascorbic acid stings on stamped skin. Resume on day +3."
    return None  # "none" or unrecognised


# ---------------------------------------------------------------------------
# Routine logic (mirrors the JSX `routineFor`)
# ---------------------------------------------------------------------------
def routine_for(d: date, is_shaving_day: bool, outdoor: bool = False,
                breakout_week: bool = False, pha_opt_in: bool = False,
                banish_day: bool = False, banish_recovery: int = 0,
                serum_choice: str = BANISH_DEFAULT_SERUM) -> dict:
    """Evidence-based 7-day rotation.

    Mon Retinal · Tue Recovery · Wed Azelaic · Thu Anua ·
    Fri Retinal · Sat Recovery (or PHA opt-in) · Sun Azelaic.
    """
    py_day = d.weekday()  # Mon=0 .. Sun=6

    label = "Recovery"
    color = "grey"
    simple_meaning = "Barrier repair night. Keeps your skin calm and less breakout-prone."
    warning = "No strong actives tonight. Recovery nights are what prevent irritation from building up."

    spf_step = (
        "Apply your outdoor water-resistant SPF50+ as the final step (reapply every 2 hours)"
        if outdoor else
        "Apply BOJ Aqua-Fresh SPF as the final step"
    )
    am = [
        "Cleanse lightly or rinse with water",
        "Apply Dr. Althea Gentle Vitamin C Serum (every other morning while phasing in)",
        "Apply ONE calming layer: Purito Centella OR COSRX Snail Mucin",
        "Apply Vanicream only if your skin feels dry",
        spf_step,
    ]
    pm = [
        "Cleanse",
        "Apply Purito Centella Serum",
        "Optional: COSRX Snail Mucin if dehydrated",
        "Seal with Vanicream Ceramide Moisturiser",
    ]

    if py_day in (0, 4):  # Mon, Fri
        label = "Retinal"
        color = "purple"
        simple_meaning = "Anti-ageing, texture, pores, and glow night."
        warning = "Do not stack with Anua, azelaic acid, or PHA tonight. Skip if you are shaving tomorrow."
        pm = [
            "Cleanse and dry your face fully",
            "Optional: thin layer of Vanicream first if your skin is reactive",
            "Apply Medik8 Crystal Retinal 6 \u2014 pea-sized for the whole face",
            "Seal with Vanicream Ceramide Moisturiser",
        ]
    elif py_day == 1:  # Tuesday — Recovery (was Optional Toner)
        label = "Recovery"
        color = "grey"
        simple_meaning = "Barrier night between Monday's retinal and Wednesday's azelaic."
        warning = "No actives tonight. This is the night your skin earns back tolerance."
    elif py_day == 2:  # Wednesday — Azelaic
        label = "Azelaic Acid"
        color = "green"
        simple_meaning = "Acne, redness, bumps, and post-acne mark night."
        warning = "Do not stack with retinal, Anua, or PHA tonight."
        pm = [
            "Cleanse and pat dry",
            "Apply Cos De BAHA Azelaic Acid 10% Serum",
            "Optional: Centella or Snail Mucin if dry",
            "Seal with Vanicream Ceramide Moisturiser",
        ]
    elif py_day == 3:  # Thursday — Anua
        label = "Anua"
        color = "pink"
        simple_meaning = "Pigmentation, uneven tone, and brightening night."
        warning = "Do not stack with retinal, azelaic, or PHA tonight."
        pm = [
            "Cleanse",
            "Apply Anua Niacinamide 10% + TXA 4% Serum",
            "Seal with Vanicream Ceramide Moisturiser",
        ]
    elif py_day == 5:  # Saturday — Recovery default; PHA opt-in if calm + no recent shave
        if pha_opt_in and not breakout_week:
            label = "PHA (opt-in)"
            color = "blue"
            simple_meaning = "Optional gentle exfoliation. Only if skin feels calm and you have not shaved in 24h."
            warning = "Skip if dry, tight, red, peeling, freshly shaved, or bumpy."
            pm = [
                "Cleanse",
                "Apply SKIN1004 Centella Toning Toner",
                "Apply Centella or Snail Mucin",
                "Seal with Vanicream Ceramide Moisturiser",
            ]
        else:
            label = "Recovery"
            color = "grey"
            simple_meaning = "Barrier night. PHA only if your skin is fully calm \u2014 otherwise rest."
            warning = "No actives. Skip the PHA toner this week if you have shaved or felt any sting."
    elif py_day == 6:  # Sunday — Azelaic (was Choose One)
        label = "Azelaic Acid"
        color = "green"
        simple_meaning = "Second azelaic night for acne and PIH."
        warning = "If skin feels irritated, switch this to a recovery night instead."
        pm = [
            "Cleanse and pat dry",
            "Apply Cos De BAHA Azelaic Acid 10% Serum",
            "Optional: Centella or Snail Mucin if dry",
            "Seal with Vanicream Ceramide Moisturiser",
        ]

    # Breakout week override: strip PHA, force calm Sat, keep Sun azelaic.
    if breakout_week and py_day == 5:
        label = "Recovery"
        color = "grey"
        simple_meaning = "Breakout week \u2014 skin needs rest, not exfoliation."
        warning = "PHA disabled this week. Centella + Vanicream only."
        pm = [
            "Cleanse",
            "Apply Purito Centella Serum",
            "Seal with Vanicream Ceramide Moisturiser",
        ]

    # ---- Banish-recovery override (days +1, +2 after a stamp) ----
    # Suppresses ALL actives. Barrier-only routine.
    if banish_recovery and not is_shaving_day and not banish_day:
        label = f"Recovery (Banish day +{banish_recovery})"
        color = "grey"
        simple_meaning = (
            f"Banish recovery — day +{banish_recovery}. The microchannels are still resealing. "
            "No actives, no exfoliants, no fragrance. Just barrier support."
        )
        warning = (
            "NO retinal, azelaic, Anua, PHA, BPO, or fragranced products. "
            "SPF 50+ is mandatory outdoors for the next 7 days post-stamp."
        )
        am = [
            "Cleanse with a mild cleanser (lukewarm water)",
            "Apply a hyaluronic acid / Centella serum on damp skin",
            "Seal with Vanicream Ceramide Moisturiser",
            "Apply SPF 50+ as the final step (mandatory \u2014 reapply every 2h outdoors)",
        ]
        if (serum_choice or "").lower() == "l-aa":
            am.insert(2, f"Skip your L-ascorbic acid serum (day +{banish_recovery} of 3)")
        pm = [
            "Cleanse gently \u2014 no scrubbing",
            "Apply a hyaluronic acid / Centella serum on damp skin",
            "Seal with Vanicream Ceramide Moisturiser",
            "No actives tonight \u2014 the barrier is still rebuilding",
        ]

    # ---- Banish-day override (the night you stamp) ----
    # PM is the stamping protocol. AM is normal but SPF 50+ from tomorrow on.
    if banish_day and not is_shaving_day:
        label = "Banish"
        color = "purple"  # rendered as blue per restricted palette
        simple_meaning = (
            "Microneedling night. Open microchannels for 4\u201312 hours \u2014 "
            "only barrier-safe products go on tonight."
        )
        warning = (
            "NO retinal, azelaic, Anua, PHA, BPO, toner, exfoliant, or fragrance tonight. "
            "Sterilise the head before AND after. Stamp 4\u20136\u00d7 per zone \u2014 lift between stamps, never drag. "
            "SPF 50+ for the next 7 days outdoors."
        )
        # AM stays whatever the weekday's normal AM is, but emphasise SPF.
        # Replace last SPF line with a force-SPF 50+ reminder.
        if am:
            am = list(am[:-1]) + [
                "Apply SPF 50+ as the final step (mandatory tonight\u2192 next 7 days)"
            ]
        # PM: the stamping protocol.
        pm_steps = [
            "Cleanse with a gentle/mild cleanser (no acids, no exfoliants)",
            "Pat dry and wait 5 minutes \u2014 skin must be 100% dry",
            "Sterilise the Banisher head with rubbing alcohol; let it dry",
            "Stamp 4\u20136\u00d7 per zone: forehead, each cheek, nose, chin",
            "Lift between stamps \u2014 never drag, slide, or roll",
            "Sterilise the head again and store dry",
        ]
        serum_step = _banish_serum_step(serum_choice)
        if serum_step:
            pm_steps.append(serum_step)
        pm_steps += [
            "Seal with Vanicream Ceramide Moisturiser",
            "Skip: toner, retinal, azelaic, Anua, PHA, BPO, fragrance, niacinamide-with-acid",
            "No SPF tonight \u2014 go straight to sleep on a clean pillowcase",
        ]
        pm = pm_steps

    if is_shaving_day:
        label = "Shaving"
        color = "teal"
        simple_meaning = (
            "Shaving day. Treat the skin like it just had a procedure \u2014 "
            "calming products only so you do not trigger razor bumps or PFB."
        )
        warning = (
            "Tonight is a recovery night. No retinal, azelaic, Anua, PHA, or vitamin C "
            "on shaved areas. With-the-grain, minimal passes, no skin stretching."
        )
        am = [
            "Cleanse gently or soften with warm water",
            "Shave with the grain \u2014 minimal passes, light pressure, no skin stretching",
            "Cool rinse and pat dry",
            "Apply Purito Centella Serum",
            "Apply Vanicream if skin feels tight",
            spf_step,
        ]
        pm = [
            "Cleanse gently",
            "If shaving at night: shave now, then cool rinse and pat dry",
            "Apply Purito Centella Serum",
            "Seal with Vanicream Ceramide Moisturiser",
            "No actives tonight \u2014 shave day = recovery day",
        ]

    # Determine the routine kind for downstream UI (cell markers, banners).
    if is_shaving_day:
        kind = "shave"
    elif banish_day:
        kind = "banish-day"
    elif banish_recovery:
        kind = "banish-recovery"
    elif breakout_week and d.weekday() == 5:
        kind = "breakout"
    else:
        kind = "normal"

    return {
        "am": am,
        "pm": pm,
        "label": label,
        "color": color,
        "simple_meaning": simple_meaning,
        "warning": warning,
        "kind": kind,
    }


# ---------------------------------------------------------------------------
# Persistence — browser localStorage
# ---------------------------------------------------------------------------
def date_key(d: date) -> str:
    return d.isoformat()


def _parse(value):
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Persistence v2: URL query param + localStorage bootstrap
#
# The previous streamlit-local-storage approach was racey: its component
# returns None on first render and cached None on rerun, so saves landed
# before reads completed and overwrote real data with empty state.
#
# New approach:
#   1. URL query param `?s=<encoded>` is the source of truth (synchronous).
#   2. On every state change we update the URL AND mirror to browser
#      localStorage via inline JS (so a fresh visit without the param can
#      auto-restore by reading localStorage and reloading with ?s=...).
# ---------------------------------------------------------------------------
STATE_PARAM = "s"
BROWSER_LS_KEY = "skincare-state-v1"


def _encode_state(state: dict) -> str:
    raw = json.dumps(state, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode().rstrip("=")


def _decode_state(s: str) -> dict:
    pad = "=" * (-len(s) % 4)
    raw = zlib.decompress(base64.urlsafe_b64decode(s + pad))
    data = json.loads(raw.decode())
    return data if isinstance(data, dict) else {}


def _collect_state() -> dict:
    return {
        "done": st.session_state.get("done", {}),
        "shave_days": st.session_state.get("shave_days", {}),
        "outdoor_days": st.session_state.get("outdoor_days", {}),
        "breakout_week": bool(st.session_state.get("breakout_week", False)),
        "patch_test": st.session_state.get("patch_test", {}),
        "intro_seen": bool(st.session_state.get("intro_seen", False)),
        "celebrated_streak": int(st.session_state.get("celebrated_streak", 0)),
        "pha_opt_in": bool(st.session_state.get("pha_opt_in", False)),
        "banish_enabled": bool(st.session_state.get("banish_enabled", False)),
        "banish_days": st.session_state.get("banish_days", {}),
        "banish_cadence": st.session_state.get("banish_cadence", BANISH_DEFAULT_CADENCE),
        "banish_recovery_days": int(st.session_state.get("banish_recovery_days", BANISH_DEFAULT_RECOVERY_DAYS)),
        "banish_head_swapped": bool(st.session_state.get("banish_head_swapped", False)),
        "banish_serum_choice": st.session_state.get("banish_serum_choice", BANISH_DEFAULT_SERUM),
    }


def hydrate(ls: LocalStorage = None) -> None:
    if st.session_state.get("_hydrated"):
        return

    qp = st.query_params.get(STATE_PARAM)
    if qp:
        try:
            data = _decode_state(qp)
            st.session_state.done = data.get("done", {}) or {}
            st.session_state.shave_days = data.get("shave_days", {}) or {}
            st.session_state.outdoor_days = data.get("outdoor_days", {}) or {}
            st.session_state.breakout_week = bool(data.get("breakout_week", False))
            st.session_state.patch_test = data.get("patch_test", {}) or {}
            st.session_state.intro_seen = bool(data.get("intro_seen", False))
            st.session_state.celebrated_streak = int(data.get("celebrated_streak", 0) or 0)
            st.session_state.pha_opt_in = bool(data.get("pha_opt_in", False))
            st.session_state.banish_enabled = bool(data.get("banish_enabled", False))
            st.session_state.banish_days = data.get("banish_days", {}) or {}
            st.session_state.banish_cadence = str(data.get("banish_cadence", BANISH_DEFAULT_CADENCE))
            st.session_state.banish_recovery_days = int(data.get("banish_recovery_days", BANISH_DEFAULT_RECOVERY_DAYS) or BANISH_DEFAULT_RECOVERY_DAYS)
            st.session_state.banish_head_swapped = bool(data.get("banish_head_swapped", False))
            st.session_state.banish_serum_choice = str(data.get("banish_serum_choice", BANISH_DEFAULT_SERUM))
            st.session_state._hydrated = True
            return
        except Exception:
            pass

    # No URL state. Inject a one-shot JS bootstrap that reads localStorage
    # and, if it has saved state, reloads the page with ?s=... in the URL.
    if not st.session_state.get("_bootstrap_attempted"):
        st.session_state._bootstrap_attempted = True
        components.html(
            f"""
            <script>
              (function() {{
                try {{
                  var top = window.parent;
                  var url = new URL(top.location.href);
                  if (url.searchParams.has({json.dumps(STATE_PARAM)})) return;
                  var v = top.localStorage.getItem({json.dumps(BROWSER_LS_KEY)});
                  if (v && v.length > 0) {{
                    url.searchParams.set({json.dumps(STATE_PARAM)}, v);
                    top.location.replace(url.toString());
                  }}
                }} catch (e) {{}}
              }})();
            </script>
            """,
            height=0,
        )

    st.session_state.setdefault("done", {})
    st.session_state.setdefault("shave_days", {})
    st.session_state.setdefault("outdoor_days", {})
    st.session_state.setdefault("breakout_week", False)
    st.session_state.setdefault("patch_test", {})
    st.session_state.setdefault("intro_seen", False)
    st.session_state.setdefault("celebrated_streak", 0)
    st.session_state.setdefault("pha_opt_in", False)
    st.session_state.setdefault("banish_enabled", False)
    st.session_state.setdefault("banish_days", {})
    st.session_state.setdefault("banish_cadence", BANISH_DEFAULT_CADENCE)
    st.session_state.setdefault("banish_recovery_days", BANISH_DEFAULT_RECOVERY_DAYS)
    st.session_state.setdefault("banish_head_swapped", False)
    st.session_state.setdefault("banish_serum_choice", BANISH_DEFAULT_SERUM)
    st.session_state._hydrated = True


def persist(ls: LocalStorage = None) -> None:
    """Write current session_state to URL + browser localStorage."""
    if not st.session_state.get("_hydrated"):
        return
    encoded = _encode_state(_collect_state())
    try:
        st.query_params[STATE_PARAM] = encoded
    except Exception:
        pass
    components.html(
        f"""
        <script>
          try {{
            window.parent.localStorage.setItem(
              {json.dumps(BROWSER_LS_KEY)},
              {json.dumps(encoded)}
            );
          }} catch (e) {{}}
        </script>
        """,
        height=0,
    )


# Back-compat wrappers — every save_* function now persists the full state.
def save_done(ls: LocalStorage = None) -> None: persist()
def save_shave(ls: LocalStorage = None) -> None: persist()
def save_outdoor(ls: LocalStorage = None) -> None: persist()
def save_breakout(ls: LocalStorage = None) -> None: persist()
def save_patch(ls: LocalStorage = None) -> None: persist()
def save_intro_seen(ls: LocalStorage = None) -> None:
    st.session_state.intro_seen = True
    persist()
def save_celebrated(ls: LocalStorage = None, streak: int = 0) -> None:
    st.session_state.celebrated_streak = int(streak)
    persist()
def save_banish(ls: LocalStorage = None) -> None: persist()


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------
def get_today() -> date:
    today = date.today()
    if today < START_DATE:
        return START_DATE
    if today > END_DATE:
        return END_DATE
    return today


def compute_progress(done: dict) -> tuple[int, int, int]:
    """Return (percent, completed_units, total_units)."""
    total = 0
    completed = 0
    d = START_DATE
    while d <= END_DATE:
        total += 2
        k = date_key(d)
        if done.get(f"{k}-am"):
            completed += 1
        if done.get(f"{k}-pm"):
            completed += 1
        d += timedelta(days=1)
    pct = round(completed / total * 100) if total else 0
    return pct, completed, total


def compute_streak(done: dict, ref: date) -> int:
    """Walk back from ref. Today only counts if BOTH AM+PM done; else
    streak picks up from yesterday."""
    streak = 0
    cursor = ref
    today = date.today()

    if cursor == today:
        k = date_key(cursor)
        if done.get(f"{k}-am") and done.get(f"{k}-pm"):
            streak += 1
        cursor -= timedelta(days=1)

    while cursor >= START_DATE:
        k = date_key(cursor)
        if done.get(f"{k}-am") and done.get(f"{k}-pm"):
            streak += 1
            cursor -= timedelta(days=1)
        else:
            break
    return streak


def compute_week_progress(done: dict, ref: date) -> tuple[int, int]:
    """Mon→Sun week containing ref. Returns (completed_slots, total_slots)."""
    monday = ref - timedelta(days=ref.weekday())
    completed = 0
    total = 0
    for offset in range(7):
        d = monday + timedelta(days=offset)
        if not (START_DATE <= d <= END_DATE):
            continue
        total += 2
        k = date_key(d)
        if done.get(f"{k}-am"):
            completed += 1
        if done.get(f"{k}-pm"):
            completed += 1
    return completed, total


def _day_completion_count(done: dict, d: date) -> int:
    k = date_key(d)
    return int(bool(done.get(f"{k}-am"))) + int(bool(done.get(f"{k}-pm")))


def _status_class(done: dict, d: date) -> str:
    count = _day_completion_count(done, d)
    if count == 2:
        return "is-done"
    if count == 1:
        return "is-partial"
    return "is-empty"


def build_stats_visuals(done: dict, ref: date) -> dict[str, str]:
    """Return small deck-style visual fragments for the stats strip."""
    recent_days = [ref - timedelta(days=offset) for offset in range(6, -1, -1)]
    dots = []
    for d in recent_days:
        classes = ["stat-dot"]
        if not (START_DATE <= d <= END_DATE):
            classes.append("is-disabled")
        else:
            classes.append(_status_class(done, d))
        if d == ref:
            classes.append("is-ref")
        dots.append(f"<span class='{' '.join(classes)}'></span>")

    monday = ref - timedelta(days=ref.weekday())
    week_chips = []
    for offset, label in enumerate(["M", "T", "W", "T", "F", "S", "S"]):
        d = monday + timedelta(days=offset)
        classes = ["week-chip"]
        if not (START_DATE <= d <= END_DATE):
            classes.append("is-disabled")
        else:
            classes.append(_status_class(done, d))
        if d == ref:
            classes.append("is-ref")
        week_chips.append(f"<span class='{' '.join(classes)}'>{label}</span>")

    pct, completed, total = compute_progress(done)
    return {
        "streak_dots": "<div class='stat-dots'>" + "".join(dots) + "</div>",
        "week_chips": "<div class='week-chips'>" + "".join(week_chips) + "</div>",
        "overall_bar": (
            "<div class='metric-bar-track'>"
            f"<div class='metric-bar-fill' style='width:{pct}%'></div>"
            "</div>"
        ),
        "overall_caption": f"{pct}% · {completed} of {total} routines done",
    }


def build_warning_html(warning: str) -> str:
    safe_warning = html.escape(warning)
    return f"""
        <div class="warn warn-rail">
            <span class="warn-glyph">!</span>
            <div>
                <div class="warn-label">Avoid tonight</div>
                <div class="warn-text">{safe_warning}</div>
            </div>
        </div>
    """


def build_tip_card_html(title: str, body: str) -> str:
    safe_title = html.escape(title)
    safe_body = html.escape(body)
    return f"""
        <div class="tip-card tip-rail">
            <span class="tip-glyph">i</span>
            <div><strong>{safe_title}.</strong> {safe_body}</div>
        </div>
    """


def build_legend_html(items: list[tuple[str, str, str, str, str]]) -> str:
    rows = []
    for color, name, when, purpose, uses in items:
        _tint, _ink, accent = PILL_COLORS[color]
        rows.append(
            "<div class='legend-item'>"
            f"<span class='legend-day'>{html.escape(when)}</span>"
            "<div class='legend-name-wrap'>"
            f"<span class='legend-pip' style='background:{accent};'></span>"
            "<div class='legend-name-text'>"
            f"<div class='legend-name'>{html.escape(name)}</div>"
            f"<div class='legend-purpose'>{html.escape(purpose)}</div>"
            "</div>"
            "</div>"
            f"<span class='legend-uses'>{html.escape(uses)}</span>"
            "</div>"
        )

    return (
        "<div class='legend-card'>"
        + "".join(rows)
        + "<div class='legend-footer'>"
        + "<span class='shave-tag'>✂ Shaving</span>"
        + "<span>Any day you mark — overrides actives with a calming routine.</span>"
        + "</div>"
        + "<div class='legend-footer'>"
        + "<span class='shave-tag' style='background:#dbe7ff;color:#1e3a8a;'>⚠ Banish</span>"
        + "<span>Microneedling night + recovery days. Barrier-only, no actives, SPF 50+ for 7 days.</span>"
        + "</div></div>"
    )


def build_day_card_html(
    d: date,
    label: str,
    color: str,
    is_selected: bool,
    is_today: bool,
    am_done: bool = False,
    pm_done: bool = False,
    shaving: bool = False,
    banish: bool = False,
    banish_recovery: int = 0,
    disabled: bool = False,
) -> str:
    if disabled:
        bg, fg, border = "#fafafa", "#9ca3af", "#e5e7eb"
    else:
        tint, ink, accent = PILL_COLORS[color]
        bg, fg, border = ("#111111", "#ffffff", "#111111") if is_selected else (tint, ink, f"{accent}55")

    classes = ["day-card"]
    if disabled:
        classes.append("is-disabled")
    if is_selected:
        classes.append("is-selected")
    if is_today:
        classes.append("is-today")

    am_cls = "cell-dot filled" if am_done else "cell-dot"
    pm_cls = "cell-dot filled" if pm_done else "cell-dot"
    if shaving:
        marker_html = "<div class='cell-shave'>✂</div>"
    elif banish:
        marker_html = "<div class='cell-shave'>⚠</div>"
    elif banish_recovery:
        marker_html = f"<div class='cell-shave'>+{banish_recovery}</div>"
    else:
        marker_html = "<div></div>"
    label_html = "" if disabled else f"<div class='cell-label'>{html.escape(label)}</div>"
    dots_html = "" if disabled else f"""
        <div class='cell-dots'>
            <span class='{am_cls}'></span>
            <span class='{pm_cls}'></span>
        </div>
    """

    return f"""
        <div class="{' '.join(classes)}" style="background:{bg};color:{fg};border-color:{border};">
            <div class="cell-top"><div class="cell-num">{d.day}</div>{marker_html}</div>
            <div class="cell-bot">{label_html}{dots_html}</div>
        </div>
    """


def initial_calendar_state() -> tuple[date, int]:
    selected = get_today()
    return selected, selected.month


def build_routine_surface_html(
    steps: list[str],
    active_slot: str,
    am_done: bool,
    pm_done: bool,
    slot_done: bool,
) -> str:
    """Render only the steps list. Tab + CTA are real Streamlit buttons."""
    is_am = active_slot == "am"  # noqa: F841
    step_rows = []
    for i, step in enumerate(steps, 1):
        cls = "step-row done" if slot_done else "step-row"
        step_rows.append(
            f"<div class='{cls}'>"
            f"<span class='step-num'><span>{i}</span></span>"
            f"<div class='step-text'>{html.escape(step)}</div>"
            "</div>"
        )
    return "<div class='routine-steps'>" + "".join(step_rows) + "</div>"

# ---------------------------------------------------------------------------
# Global styles
# ---------------------------------------------------------------------------
def inject_styles() -> None:
    css_rules = []
    for name, (tint, ink, accent) in PILL_COLORS.items():
        css_rules.append(
            f"""
            div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor.is-{name}) > div[data-testid="stElementContainer"]:has(div.stButton) div.stButton > button {{
                background: {tint};
                color: {ink};
                border: 1px solid {accent}55;
            }}
            div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor.is-{name}) > div[data-testid="stElementContainer"]:has(div.stButton) div.stButton > button:hover {{
                background: {tint};
                border-color: {accent};
                color: {ink};
            }}
            div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor.is-{name}.is-selected) > div[data-testid="stElementContainer"]:has(div.stButton) div.stButton > button {{
                background: #111111;
                color: #ffffff;
                border-color: #111111;
            }}
            """
        )
    color_rules = "\n".join(css_rules)

    style_block = f"""
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
        :root {{
            --ink: #111111;
            --ink-2: #1f2937;
            --ink-3: #4b5563;
            --muted: #6b7280;
            --faint: #9ca3af;
            --hairline: #e5e7eb;
            --bg-track: #f3f4f6;
            --bg-subtle: #f9fafb;
            --green: #16a34a;
            --green-tint: #d4f4dd;
            --green-ink: #14532d;
            --blue: #2563eb;
            --blue-tint: #dbe7ff;
            --red: #dc2626;
            --red-tint: #fde0e0;
            --shadow-card: 0 1px 0 rgba(0,0,0,0.03), 0 1px 2px rgba(0,0,0,0.04);
            --shadow-hover: 0 2px 8px rgba(0,0,0,0.06);
            --shadow-pop: 0 8px 24px rgba(0,0,0,0.10);
        }}

        /* ---------- Reset Streamlit chrome ---------- */
        #MainMenu, footer, header[data-testid="stHeader"] {{ visibility: hidden; height: 0; }}
        .stDeployButton, [data-testid="stToolbar"] {{ display: none !important; }}

        /* ---------- Background & font ---------- */
        html, body, [data-testid="stAppViewContainer"] {{
            font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
            background: #ffffff !important;
            color: #1f2937;
        }}
        [data-testid="stAppViewContainer"] > .main {{ background: transparent; }}
        .block-container {{
            padding-top: 2.25rem;
            padding-bottom: 4rem;
            max-width: 1280px;
        }}

        /* ---------- Typography ---------- */
        h1, h2, h3, h4 {{ font-family: 'Inter', system-ui, sans-serif; font-weight: 800; letter-spacing: -0.01em; }}
        .label-tiny {{
            font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
            text-transform: uppercase; color: #6b7280;
        }}

        /* ---------- Cards ---------- */
        .surface-tight {{
            background: #ffffff; border-radius: 12px; padding: 14px 16px;
            box-shadow: 0 1px 0 rgba(0,0,0,0.03), 0 1px 2px rgba(0,0,0,0.04);
        }}

        /* ---------- Header ---------- */
        .app-header {{ display: flex; align-items: center; gap: 14px; margin-bottom: 6px; }}
        .app-glyph {{ font-size: 28px; color: #111111; line-height: 1; }}
        .app-title {{ font-size: 26px; font-weight: 800; color: #111111; line-height: 1.1; letter-spacing: -0.01em; }}
        .app-subtitle {{ color: #6b7280; font-size: 14px; font-weight: 500; margin-top: 2px; }}

        /* ---------- Metric cards ---------- */
        .metric {{ background: #ffffff; border-radius: 12px; padding: 16px;
                   border: 1px solid #e5e7eb;
                   box-shadow: 0 1px 0 rgba(0,0,0,0.03), 0 1px 2px rgba(0,0,0,0.04); }}
        .metric-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }}
        .metric .m-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
                            text-transform: uppercase; color: #6b7280; }}
        .metric .m-value {{ font-size: 32px; font-weight: 800; color: #111111; margin-top: 4px;
                            line-height: 1.1; font-variant-numeric: tabular-nums; }}
        .metric .m-cap {{ font-size: 12px; color: #9ca3af; margin-top: 2px; }}
        .metric .m-kicker {{ font-size: 12px; color: #9ca3af; white-space: nowrap; }}
        .metric-visual {{ margin-top: 12px; min-height: 24px; display: flex; align-items: center; }}
        .metric-subcap {{ font-size: 12px; color: #6b7280; margin-top: 8px; line-height: 1.4; }}
        .metric-subcap b {{ color: #111111; }}
        .stat-dots {{ display: flex; gap: 6px; align-items: center; }}
        .stat-dot {{
            width: 14px; height: 14px; border-radius: 50%;
            background: #f3f4f6; border: 1px solid #e5e7eb;
            display: inline-block; flex: 0 0 auto;
        }}
        .stat-dot.is-done {{ background: #16a34a; border-color: #16a34a; }}
        .stat-dot.is-partial {{
            background: linear-gradient(90deg, #16a34a 50%, #f3f4f6 50%);
            border-color: #16a34a;
        }}
        .stat-dot.is-ref {{ outline: 2px solid #111111; outline-offset: 2px; }}
        .stat-dot.is-disabled {{ opacity: 0.35; }}
        .week-chips {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; width: 100%; }}
        .week-chip {{
            min-width: 0; height: 26px; border-radius: 8px;
            background: #f3f4f6; color: #9ca3af;
            display: inline-flex; align-items: center; justify-content: center;
            font-size: 11px; font-weight: 700;
        }}
        .week-chip.is-done {{ background: #111111; color: #ffffff; }}
        .week-chip.is-partial {{
            background: #d4f4dd; color: #14532d;
            box-shadow: inset 0 0 0 1px rgba(22,163,74,0.25);
        }}
        .week-chip.is-ref {{ outline: 2px solid #111111; outline-offset: 2px; }}
        .week-chip.is-disabled {{ opacity: 0.35; }}
        .metric-bar-track {{ height: 10px; background: #f3f4f6; border-radius: 999px; overflow: hidden; width: 100%; }}
        .metric-bar-fill {{ height: 100%; background: #111111; border-radius: 999px; }}

        /* ---------- Slim progress bar ---------- */
        .slim-track {{ height: 6px; background: #f3f4f6; border-radius: 999px; overflow: hidden; }}
        .slim-fill {{ height: 100%; background: #111111; border-radius: 999px; }}

        /* ---------- Calendar grid ---------- */
        .cell-anchor {{ display: none; }}

        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) {{
            position: relative;
            min-height: 96px;
        }}
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) > div[data-testid="stElementContainer"]:has(.day-card) {{
            position: relative;
            z-index: 1;
        }}
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) > div[data-testid="stElementContainer"]:has(div.stButton) {{
            position: absolute;
            inset: 0;
            z-index: 3;
            height: 96px;
        }}
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) > div[data-testid="stElementContainer"]:has(div.stButton) div.stButton,
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) > div[data-testid="stElementContainer"]:has(div.stButton) div.stButton > button {{
            height: 96px !important;
        }}
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) > div[data-testid="stElementContainer"]:has(div.stButton) div.stButton > button {{
            opacity: 0 !important;
            height: 96px !important;
            padding: 10px 12px !important;
            border-radius: 12px !important;
            font-family: 'Inter', sans-serif !important;
            font-weight: 700 !important;
            font-size: 18px !important;
            text-align: left !important;
            display: flex !important;
            align-items: flex-start !important;
            justify-content: flex-start !important;
            transition: transform 120ms ease, box-shadow 120ms ease, background 160ms ease;
            position: relative;
        }}
        .day-card {{
            height: 96px;
            padding: 10px 12px;
            border-radius: 12px;
            border: 1px solid;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 120ms ease, box-shadow 120ms ease, background 160ms ease;
        }}
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor):hover .day-card:not(.is-disabled):not(.is-selected) {{
            transform: translateY(-2px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .day-card.is-today {{
            outline: 2px solid #111111;
            outline-offset: 2px;
        }}
        .day-card.is-selected {{
            transform: scale(1.02);
            box-shadow: 0 8px 24px rgba(0,0,0,0.10);
        }}
        .day-card.is-disabled {{
            border-style: dashed;
            box-shadow: none !important;
            cursor: not-allowed !important;
            transform: none !important;
        }}

        .cell-wrap {{ position: relative; }}
        .cal-spacer {{ height: 96px; }}
        .cell-overlay {{
            position: absolute; inset: 0; pointer-events: none;
            padding: 10px 12px;
            display: flex; flex-direction: column; justify-content: space-between;
        }}
        .cell-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
        .cell-shave {{ font-size: 13px; color: #14532d; font-weight: 700; }}
        .cell-bot {{ display: flex; flex-direction: column; gap: 4px; }}
        .cell-label {{ font-size: 11px; font-weight: 600; letter-spacing: 0.02em; opacity: 0.85; }}
        .cell-dots {{ display: flex; gap: 4px; }}
        .cell-dot {{ width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid currentColor; }}
        .cell-dot.filled {{ background: currentColor; }}

        {color_rules}

        /* When selected, force overlay text to white */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor.is-selected) .cell-overlay {{ color: #ffffff !important; }}
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor.is-selected) .cell-shave {{ color: #ffffff !important; }}

        /* ---------- Hero ---------- */
        .hero {{
            border-radius: 16px; padding: 22px;
            position: relative; overflow: hidden;
        }}
        .hero .h-meta {{ font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.7; font-weight: 700; }}
        .hero .h-title {{ font-size: 30px; font-weight: 800; margin-top: 4px; line-height: 1.1; letter-spacing: -0.01em; }}
        .hero .h-meaning {{ font-size: 15px; font-weight: 600; margin-top: 10px; line-height: 1.5; opacity: 0.9; }}

        /* ---------- Warning ---------- */
        .warn {{
            background: #ffffff; color: #111111; border-radius: 12px;
            padding: 14px 16px; display: grid;
            grid-template-columns: 32px 1fr; gap: 14px; align-items: flex-start;
            font-size: 13px; font-weight: 500; line-height: 1.5;
            border: 1px solid #e5e7eb;
            box-shadow: 0 1px 0 rgba(0,0,0,0.03), 0 1px 2px rgba(0,0,0,0.04);
            position: relative; overflow: hidden;
        }}
        .warn::before {{
            content: ""; position: absolute; left: 0; top: 0; bottom: 0;
            width: 3px; background: #dc2626;
        }}
        .warn-glyph {{
            width: 32px; height: 32px; border-radius: 50%;
            display: inline-flex; align-items: center; justify-content: center;
            background: #fde0e0; color: #dc2626;
            border: 1px solid rgba(220,38,38,0.2);
            font-size: 16px; font-weight: 800;
        }}
        .warn-label {{
            font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; color: #dc2626; margin-bottom: 2px;
        }}
        .warn-text {{ color: #111111; }}

        /* ---------- Section labels & step rows ---------- */
        .section-label {{
            font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; color: #111111; margin: 18px 0 8px;
        }}
        .am-pm-tabs {{ display: flex; border-bottom: 1px solid #e5e7eb; }}
        .am-pm-tab {{
            flex: 1; text-align: center; padding: 12px 14px;
            font-size: 13px; font-weight: 700; letter-spacing: 0.04em;
            color: #6b7280; border-bottom: 2px solid transparent; margin-bottom: -1px;
        }}
        .am-pm-tab.active {{ color: #111111; border-bottom: 2px solid #111111; }}
        .am-pm-tab .ok {{ color: #16a34a; margin-left: 6px; }}

        /* ---------- Shave pill (Streamlit button styled as outline pill) ---------- */
        .shave-pill-anchor {{ display: none; }}
        div[data-testid="stVerticalBlock"]:has(> div > div > .shave-pill-anchor) + div div.stButton > button,
        div.stButton:has(+ * .shave-pill-anchor) > button {{
            /* fallback selector — we apply via the anchor sibling pattern below */
        }}
        /* Real styling: target stButton that immediately follows our anchor span. */
        .shave-pill-anchor.shave-pill-idle + div div.stButton > button,
        div:has(> .shave-pill-anchor.shave-pill-idle) ~ div div.stButton > button:first-of-type {{
            background: transparent !important;
            color: #14532d !important;
            border: 1.5px solid #14532d !important;
            border-radius: 999px !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            letter-spacing: 0.04em !important;
            padding: 6px 14px !important;
            min-height: auto !important;
            box-shadow: none !important;
        }}
        .shave-pill-anchor.shave-pill-active + div div.stButton > button,
        div:has(> .shave-pill-anchor.shave-pill-active) ~ div div.stButton > button:first-of-type {{
            background: #14532d !important;
            color: #ffffff !important;
            border: 1.5px solid #14532d !important;
            border-radius: 999px !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            letter-spacing: 0.04em !important;
            padding: 6px 14px !important;
            min-height: auto !important;
            box-shadow: none !important;
        }}
        div.st-key-shave-toggle button {{
            background: transparent !important;
            color: #14532d !important;
            border: 1.5px solid #14532d !important;
            border-radius: 999px !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            letter-spacing: 0.04em !important;
            min-height: 40px !important;
            box-shadow: none !important;
        }}
        [data-testid="stAppViewContainer"]:has(.shave-pill-anchor.shave-pill-active) div.st-key-shave-toggle button {{
            background: #14532d !important;
            color: #ffffff !important;
        }}
        .routine-surface {{
            background: #ffffff;
            border-radius: 12px;
            border: 1px solid #e5e7eb;
            box-shadow: 0 1px 0 rgba(0,0,0,0.03), 0 1px 2px rgba(0,0,0,0.04);
            overflow: hidden;
            margin-top: 14px;
        }}
        .routine-steps {{
            padding: 6px 16px 10px;
            background: #ffffff;
        }}
        .step-row {{
            display: flex; align-items: flex-start; gap: 14px;
            padding: 12px 0; border-bottom: 1px solid #e5e7eb;
            font-size: 14px; color: #1f2937; line-height: 1.5;
        }}
        .step-row:last-child {{ border-bottom: none; }}
        .step-num {{
            width: 24px; height: 24px; border-radius: 50%;
            background: #f3f4f6; color: #4b5563;
            font-size: 12px; font-weight: 700;
            display: inline-flex; align-items: center; justify-content: center;
            flex: 0 0 auto;
            transition: all 160ms ease;
        }}
        .step-row.done .step-num {{
            background: #16a34a; color: #ffffff;
        }}
        .step-row.done .step-num span {{ display: none; }}
        .step-row.done .step-num::before {{ content: "✓"; font-size: 13px; }}
        .step-row.done .step-text {{
            color: #9ca3af;
            text-decoration: line-through;
            text-decoration-thickness: 1px;
        }}
        .step-text {{ flex: 1; }}

        /* Tab buttons (real Streamlit buttons) */
        div.st-key-tab-am button,
        div.st-key-tab-pm button {{
            background: #ffffff !important;
            color: #6b7280 !important;
            border: 0 !important;
            border-bottom: 2px solid transparent !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            min-height: 44px !important;
            font-weight: 700 !important;
            letter-spacing: 0.04em !important;
            font-size: 13px !important;
        }}
        div.st-key-tab-am button[kind="primary"],
        div.st-key-tab-pm button[kind="primary"],
        div.st-key-tab-am button[data-testid="stBaseButton-primary"],
        div.st-key-tab-pm button[data-testid="stBaseButton-primary"] {{
            background: #ffffff !important;
            color: #111111 !important;
            border-bottom-color: #111111 !important;
        }}
        /* Tighten the gap between tab row and steps */
        div[data-testid="stHorizontalBlock"]:has(div.st-key-tab-am) {{
            border-bottom: 1px solid #e5e7eb;
            margin-bottom: 0;
        }}
        /* Complete CTA */
        div.st-key-complete-am button,
        div.st-key-complete-pm button {{
            min-height: 44px !important;
            font-weight: 700 !important;
        }}

        /* ---------- Sidebar ---------- */
        [data-testid="stSidebar"] {{ background: #ffffff !important; border-right: 1px solid #e5e7eb; }}
        [data-testid="stSidebar"] .block-container {{ padding-top: 1.5rem; }}
        .legend-card {{
            background: #ffffff;
            border-radius: 14px;
            border: 1px solid #e5e7eb;
            box-shadow: 0 1px 0 rgba(0,0,0,0.03), 0 1px 2px rgba(0,0,0,0.04);
            overflow: hidden;
            margin-top: 8px;
        }}
        .legend-item {{
            display: grid;
            grid-template-columns: 58px minmax(0, 1fr);
            align-items: center;
            gap: 12px;
            padding: 12px 14px;
            border-bottom: 1px solid #e5e7eb;
            transition: background 160ms ease;
        }}
        .legend-item:hover {{ background: #f9fafb; }}
        .legend-day {{
            font-family: ui-monospace, Menlo, monospace;
            font-size: 10px; font-weight: 700;
            letter-spacing: 0.08em; color: #6b7280;
        }}
        .legend-name-wrap {{
            display: flex; align-items: center; gap: 10px; min-width: 0;
        }}
        .legend-pip {{
            width: 8px; height: 32px; border-radius: 999px; flex: 0 0 auto;
        }}
        .legend-name-text {{ min-width: 0; }}
        .legend-name {{
            font-size: 13px; font-weight: 700; color: #111111;
            line-height: 1.2;
        }}
        .legend-purpose {{
            font-size: 11px; color: #6b7280;
            margin-top: 3px; line-height: 1.3;
        }}
        .legend-uses {{
            grid-column: 2;
            font-size: 11px; color: #6b7280;
            line-height: 1.35;
        }}
        .legend-footer {{
            display: flex; align-items: center; gap: 8px;
            padding: 12px 14px;
            background: #f9fafb;
            border-top: 1px solid #e5e7eb;
            font-size: 12px; color: #6b7280;
            line-height: 1.4;
        }}
        .shave-tag {{
            display: inline-flex; align-items: center; gap: 5px;
            padding: 3px 9px; border-radius: 999px;
            background: #d4f4dd; color: #14532d;
            font-weight: 700; font-size: 10px;
            letter-spacing: 0.06em; text-transform: uppercase;
            white-space: nowrap;
        }}
        .product-row {{
            font-size: 13px; padding: 6px 0; color: #1f2937;
            border-bottom: 1px solid #e5e7eb;
        }}
        .product-row:last-child {{ border-bottom: none; }}
        .tip-card {{
            background: #ffffff; border-radius: 12px; padding: 14px 16px;
            font-size: 12px; color: #4b5563; line-height: 1.5; margin-bottom: 8px;
            border: 1px solid #e5e7eb;
            box-shadow: 0 1px 0 rgba(0,0,0,0.03), 0 1px 2px rgba(0,0,0,0.04);
            display: grid; grid-template-columns: 32px 1fr; gap: 14px;
            position: relative; overflow: hidden;
        }}
        .tip-card::before {{
            content: ""; position: absolute; left: 0; top: 0; bottom: 0;
            width: 3px; background: #2563eb;
        }}
        .tip-card strong {{ color: #111111; }}
        .tip-glyph {{
            width: 32px; height: 32px; border-radius: 50%;
            display: inline-flex; align-items: center; justify-content: center;
            background: #dbe7ff; color: #2563eb;
            border: 1px solid rgba(37,99,235,0.2);
            font-size: 14px; font-weight: 800; font-style: normal;
        }}
        .tip-dot-shell {{ display: none; }}
        div.st-key-tip-dot-0, div.st-key-tip-dot-1, div.st-key-tip-dot-2 {{
            display: flex !important;
            justify-content: flex-end;
        }}
        div.st-key-tip-dot-0 button,
        div.st-key-tip-dot-1 button,
        div.st-key-tip-dot-2 button {{
            min-height: 18px !important;
            width: 18px !important;
            height: 18px !important;
            padding: 0 !important;
            border-radius: 999px !important;
            box-shadow: none !important;
            font-size: 11px !important;
            line-height: 1 !important;
            color: #111111 !important;
            background: #ffffff !important;
            border: 1px solid #e5e7eb !important;
        }}

        /* ---------- Buttons ---------- */
        div.stButton > button {{
            font-family: 'Inter', sans-serif !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            transition: all 160ms ease;
        }}
        div.stButton > button[data-testid="stBaseButton-primary"] {{
            background: #111111 !important;
            color: #ffffff !important;
            border-color: #111111 !important;
        }}
        div.st-key-reset-confirm button[data-testid="stBaseButton-primary"] {{
            background: #dc2626 !important;
            border-color: #dc2626 !important;
        }}
        div.st-key-tab-am button,
        div.st-key-tab-pm button {{
            background: #ffffff !important;
            color: #6b7280 !important;
            border: none !important;
            border-bottom: 2px solid transparent !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            min-height: 44px !important;
            letter-spacing: 0.04em !important;
        }}
        div.st-key-tab-am button[data-testid="stBaseButton-primary"],
        div.st-key-tab-pm button[data-testid="stBaseButton-primary"] {{
            background: #ffffff !important;
            color: #111111 !important;
            border-bottom-color: #111111 !important;
        }}
        div.stButton > button:hover {{ transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.06); }}

        /* ---------- Intro banner ---------- */
        .intro-banner {{
            display: flex; gap: 14px; align-items: flex-start;
            background: linear-gradient(135deg, #fef7d6 0%, #dbe7ff 100%);
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 16px 18px;
            margin: 8px 0 12px;
            box-shadow: var(--shadow-card);
        }}
        .intro-icon {{ font-size: 22px; line-height: 1; }}
        .intro-title {{ font-weight: 800; font-size: 15px; color: #111111; margin-bottom: 4px; }}
        .intro-text {{ font-size: 13px; color: #1f2937; line-height: 1.5; }}
        div.st-key-intro-dismiss button {{
            background: #111111 !important; color: #ffffff !important;
            border: 0 !important; border-radius: 999px !important;
            padding: 6px 18px !important; min-height: 36px !important;
            font-weight: 700 !important;
        }}

        /* ---------- Streak celebration ---------- */
        .celebrate {{
            position: relative; overflow: hidden;
            background: linear-gradient(135deg, #d4f4dd 0%, #fef7d6 100%);
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 14px 18px;
            margin: 6px 0 14px;
            box-shadow: var(--shadow-pop);
            animation: celebrate-pop 420ms cubic-bezier(.2,1.3,.4,1);
        }}
        .celebrate-body {{ display: flex; gap: 14px; align-items: center; position: relative; z-index: 2; }}
        .celebrate-emoji {{ font-size: 28px; line-height: 1; }}
        .celebrate-title {{ font-weight: 800; font-size: 16px; color: #14532d; }}
        .celebrate-text {{ font-size: 13px; color: #1f2937; }}
        .celebrate-confetti {{
            position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 1;
        }}
        .confetti-piece {{
            position: absolute; top: -10px;
            width: 8px; height: 12px; border-radius: 2px;
            animation: confetti-fall 1.6s ease-in forwards;
        }}
        .confetti-piece.c0 {{ background: #f5c518; }}
        .confetti-piece.c1 {{ background: #16a34a; }}
        .confetti-piece.c2 {{ background: #2563eb; }}
        .confetti-piece.c3 {{ background: #dc2626; }}
        .confetti-piece.c4 {{ background: #111111; }}
        @keyframes confetti-fall {{
            0%   {{ transform: translateY(-20px) rotate(0deg);   opacity: 1; }}
            100% {{ transform: translateY(140px) rotate(540deg); opacity: 0; }}
        }}
        @keyframes celebrate-pop {{
            0%   {{ transform: scale(0.96); opacity: 0; }}
            100% {{ transform: scale(1);    opacity: 1; }}
        }}

        /* ---------- Day nav strip ---------- */
        .day-nav-label {{
            display: flex; flex-direction: column; align-items: center;
            justify-content: center; min-height: 38px;
        }}
        .day-nav-date {{
            font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; color: #6b7280;
        }}
        .day-nav-rel {{
            font-size: 12px; font-weight: 700; color: #111111;
            margin-top: 1px;
        }}
        div.st-key-prev-day button,
        div.st-key-next-day button {{
            min-height: 38px !important;
            background: #ffffff !important;
            color: #111111 !important;
            border: 1px solid #e5e7eb !important;
            font-size: 18px !important; font-weight: 700 !important;
            padding: 0 !important;
        }}
        div.st-key-prev-day button:disabled,
        div.st-key-next-day button:disabled {{
            color: #d1d5db !important; background: #f9fafb !important;
        }}

        /* ---------- Tomorrow preview ---------- */
        .tomorrow-preview {{
            display: flex; align-items: center; gap: 12px;
            background: #ffffff; border: 1px solid #e5e7eb;
            border-radius: 12px; padding: 12px 14px;
            margin-top: 12px;
            box-shadow: var(--shadow-card);
        }}
        .tomorrow-pip {{
            width: 6px; height: 28px; border-radius: 999px; flex: 0 0 auto;
        }}
        .tomorrow-text {{ display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }}
        .tomorrow-label {{
            font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; color: #6b7280;
        }}
        .tomorrow-name {{ font-size: 14px; font-weight: 700; color: #111111; }}
        .tomorrow-arrow {{ color: #9ca3af; font-size: 18px; }}

        /* ---------- Sticky today panel on desktop ---------- */
        @media (min-width: 1024px) {{
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) {{
                position: sticky;
                top: 16px;
                align-self: flex-start;
                max-height: calc(100vh - 32px);
                overflow-y: auto;
            }}
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2)::-webkit-scrollbar {{
                width: 6px;
            }}
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2)::-webkit-scrollbar-thumb {{
                background: #e5e7eb; border-radius: 999px;
            }}
        }}

        /* ---------- Reduced motion ---------- */
        @media (prefers-reduced-motion: reduce) {{
            * {{ transition: none !important; transform: none !important; }}
        }}

        /* ---------- Mobile (≤ 720px) ---------- */
        @media (max-width: 720px) {{
            .block-container {{
                padding-top: 1rem !important;
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
                padding-bottom: 6rem !important;
            }}
            .app-title {{ font-size: 22px !important; }}
            .app-subtitle {{ font-size: 13px !important; }}
            .app-glyph {{ font-size: 22px !important; }}

            /* Stack stats vertically on small screens */
            div[data-testid="stHorizontalBlock"]:has(.metric) {{
                flex-direction: column !important;
                gap: 8px !important;
            }}
            div[data-testid="stHorizontalBlock"]:has(.metric) > div[data-testid="column"] {{
                width: 100% !important; flex: 1 1 100% !important;
            }}
            .metric {{ padding: 12px 14px; }}
            .metric .m-value {{ font-size: 24px; }}
            .metric-visual {{ margin-top: 8px; }}
            .metric-subcap {{ font-size: 11px; }}

            /* Stack calendar above today panel — default flow already does
               this since Streamlit columns become rows on mobile */
            div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor),
            .day-card,
            div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) > div[data-testid="stElementContainer"]:has(div.stButton),
            div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) > div[data-testid="stElementContainer"]:has(div.stButton) div.stButton,
            div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .cell-anchor) > div[data-testid="stElementContainer"]:has(div.stButton) div.stButton > button {{
                min-height: 64px !important;
                height: 64px !important;
                font-size: 14px !important;
            }}
            .cal-spacer {{ height: 64px; }}
            .cell-label, .cell-shave {{ display: none; }}
            .cell-num {{ font-size: 15px; }}

            /* Hero & content */
            .hero {{ padding: 18px; border-radius: 14px; }}
            .hero .h-title {{ font-size: 24px; }}
            .hero .h-meaning {{ font-size: 14px; }}
            .step-row {{ padding: 14px 0; }}  /* bigger touch targets */
            div.stButton > button {{ min-height: 44px !important; }}

            /* Hide the desktop-only "How this works" expander on mobile to declutter */
            div[data-testid="stExpander"] {{ display: none; }}

            /* Legend table compresses gracefully */
            .legend-item {{ grid-template-columns: 48px minmax(0, 1fr); padding: 10px 12px; }}
            .legend-uses {{ font-size: 10px; }}
        }}
        </style>
        """
    try:
        st.html(style_block)
    except AttributeError:
        # Older Streamlit fallback
        st.markdown(style_block, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# UI sections
# ---------------------------------------------------------------------------
def render_header() -> None:
    col_l, col_r = st.columns([5, 1])
    with col_l:
        st.markdown(
            """
            <div class="app-header">
                <div class="app-glyph">✷</div>
                <div>
                    <div class="app-title">Skincare Calendar</div>
                    <div class="app-subtitle">A calmer way to keep your routine on track.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_r:
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        if st.button("Today", use_container_width=True, key="jump-today"):
            st.session_state.selected_date = get_today()
            st.session_state.month = st.session_state.selected_date.month
            st.rerun()

    with st.expander("How this works"):
        st.write(
            "This view does not weaken your routine. It only explains the routine "
            "in clearer steps. Shaving days are different because shaving can irritate the skin, "
            "so the calendar switches that day to a calming routine. Your progress is saved in "
            "this browser."
        )
        st.markdown(
            "**Keyboard shortcuts:** "
            "`J` previous day · `K` next day · `T` today · "
            "`M` morning tab · `N` night tab · `A` toggle morning · `P` toggle night."
        )


def render_intro_banner(ls: LocalStorage) -> None:
    if st.session_state.get("intro_seen"):
        return
    st.markdown(
        """
        <div class="intro-banner">
            <div class="intro-icon">✨</div>
            <div class="intro-body">
                <div class="intro-title">Welcome — here's the gist</div>
                <div class="intro-text">
                    Tap any day to see its routine. Mark <b>Morning</b> and <b>Night</b>
                    when you finish. Mark <b>shaving days</b> for a calming routine.
                    Progress is saved in this browser — no account needed.
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Got it", key="intro-dismiss", use_container_width=False):
        st.session_state.intro_seen = True
        save_intro_seen(ls)
        st.rerun()


def render_celebration(ls: LocalStorage, streak: int) -> None:
    """Show a one-shot confetti banner when crossing a streak milestone."""
    last = int(st.session_state.get("celebrated_streak", 0) or 0)
    if streak <= last or streak not in STREAK_MILESTONES:
        return
    pieces = "".join(
        f"<span class='confetti-piece c{i % 5}' style='left:{i * 7 % 100}%;animation-delay:{i * 0.08:.2f}s'></span>"
        for i in range(28)
    )
    msg = {
        3: "3 days in a row — nice start.",
        7: "A full week. Skin loves consistency.",
        14: "Two weeks. You're building a real habit.",
        30: "30 days! Your routine is officially a routine.",
        60: "60 days. Glow incoming.",
        100: "100 days. Legendary.",
    }.get(streak, f"{streak} days in a row.")
    st.markdown(
        f"""
        <div class="celebrate">
            <div class="celebrate-confetti">{pieces}</div>
            <div class="celebrate-body">
                <div class="celebrate-emoji">🎉</div>
                <div>
                    <div class="celebrate-title">{streak}-day streak</div>
                    <div class="celebrate-text">{msg}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.session_state.celebrated_streak = streak
    save_celebrated(ls, streak)


def inject_keyboard_shortcuts() -> None:
    js = """
    <script>
    (function() {
      const doc = window.parent ? window.parent.document : document;
      if (doc._scKeysAttached) return;
      doc._scKeysAttached = true;
      const map = {
        'j': 'prev-day', 'k': 'next-day', 't': 'jump-today',
        'm': 'tab-am', 'n': 'tab-pm',
        'a': 'complete-am', 'p': 'complete-pm'
      };
      doc.addEventListener('keydown', function(e) {
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        const t = e.target;
        if (!t) return;
        const tag = (t.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || t.isContentEditable) return;
        const key = map[e.key.toLowerCase()];
        if (!key) return;
        const btn = doc.querySelector('.st-key-' + key + ' button');
        if (btn) { e.preventDefault(); btn.click(); }
      });
    })();
    </script>
    """
    try:
        st.html(js)
    except AttributeError:
        st.markdown(js, unsafe_allow_html=True)


def render_stats_strip(done: dict) -> None:
    today = get_today()
    streak = compute_streak(done, today)
    week_done, week_total = compute_week_progress(done, today)
    pct, _completed, total = compute_progress(done)
    days_total = total // 2
    visuals = build_stats_visuals(done, today)

    cols = st.columns(3)
    no_progress = pct == 0 and streak == 0 and week_done == 0
    streak_subcap = (
        "Start tonight — one routine begins your streak." if no_progress
        else f"<b>{streak}</b> {'day' if streak == 1 else 'days'} in a row · AM + PM"
    )
    overall_subcap = (
        "You’re at the start of the program — plenty of time." if no_progress
        else visuals["overall_caption"]
    )
    cards = [
        (
            "Streak",
            f"{streak} {'day' if streak == 1 else 'days'}",
            "last 7 days",
            visuals["streak_dots"],
            streak_subcap,
        ),
        ("This week", f"{week_done} / {week_total}" if week_total else "—",
         "Mon → Sun", visuals["week_chips"],
         (f"<b>{week_done}</b> of {week_total} routines logged" if week_total else "No routines this week")),
        ("Overall", f"{pct}%", f"{days_total} days total", visuals["overall_bar"],
         overall_subcap),
    ]
    for col, (lbl, val, cap, visual, subcap) in zip(cols, cards):
        with col:
            st.markdown(
                f"""
                <div class="metric">
                    <div class="metric-head">
                        <div class="m-label">{lbl}</div>
                        <div class="m-kicker">{cap}</div>
                    </div>
                    <div class="m-value">{val}</div>
                    <div class="metric-visual">{visual}</div>
                    <div class="metric-subcap">{subcap}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_month_nav() -> None:
    cols = st.columns([1, 3, 1])
    with cols[0]:
        if st.button("‹", key="prev-month",
                     disabled=st.session_state.month <= START_DATE.month,
                     use_container_width=True):
            st.session_state.month -= 1
            st.session_state.selected_date = date(
                YEAR, st.session_state.month,
                26 if st.session_state.month == START_DATE.month else 1,
            )
            st.rerun()
    with cols[1]:
        values = list(range(START_DATE.month, 13))
        idx = values.index(st.session_state.month) if st.session_state.month in values else 0
        chosen = st.selectbox(
            "Month",
            options=values,
            index=idx,
            format_func=lambda m: f"{MONTH_NAMES[m - 1]} {YEAR}",
            label_visibility="collapsed",
            key="month-select",
        )
        if chosen != st.session_state.month:
            st.session_state.month = chosen
            st.session_state.selected_date = date(YEAR, chosen, 1)
            st.rerun()
    with cols[2]:
        if st.button("›", key="next-month",
                     disabled=st.session_state.month >= 12,
                     use_container_width=True):
            st.session_state.month += 1
            st.session_state.selected_date = date(YEAR, st.session_state.month, 1)
            st.rerun()


def render_calendar(month: int) -> None:
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(YEAR, month)
    today_real = date.today()

    header_cols = st.columns(7)
    for i, name in enumerate(DAY_NAMES_SHORT):
        header_cols[i].markdown(
            f"<div class='label-tiny' style='text-align:center;'>{name}</div>",
            unsafe_allow_html=True,
        )

    selected = st.session_state.selected_date

    for w_idx, week in enumerate(weeks):
        cols = st.columns(7, gap="small")
        for i, d in enumerate(week):
            with cols[i]:
                in_range = START_DATE <= d <= END_DATE
                if d.month != month:
                    # Spillover: blank spacer to preserve grid shape
                    st.markdown("<div class='cal-spacer'></div>", unsafe_allow_html=True)
                    continue
                if not in_range:
                    # In-month but out of program window: calm dashed tile
                    st.markdown("<span class='cell-anchor is-disabled'></span>",
                                unsafe_allow_html=True)
                    st.markdown(
                        build_day_card_html(
                            d=d,
                            label="",
                            color="grey",
                            is_selected=False,
                            is_today=False,
                            disabled=True,
                        ),
                        unsafe_allow_html=True,
                    )
                    st.button(str(d.day), key=f"oor-{w_idx}-{i}", disabled=True,
                              use_container_width=True)
                    continue

                k = date_key(d)
                shaving = bool(st.session_state.shave_days.get(k))
                outdoor = bool(st.session_state.get("outdoor_days", {}).get(k))
                breakout = bool(st.session_state.get("breakout_week"))
                pha_opt_in_now = bool(st.session_state.get("pha_opt_in"))
                banish_enabled = bool(st.session_state.get("banish_enabled"))
                banish_map = st.session_state.get("banish_days", {}) if banish_enabled else {}
                recovery_days_n = int(st.session_state.get("banish_recovery_days", BANISH_DEFAULT_RECOVERY_DAYS))
                serum_choice = str(st.session_state.get("banish_serum_choice", BANISH_DEFAULT_SERUM))
                banish_today = is_banish_day(d, banish_map)
                banish_recov = banish_recovery_offset(d, banish_map, recovery_days_n)
                r = routine_for(
                    d, shaving, outdoor=outdoor, breakout_week=breakout,
                    pha_opt_in=pha_opt_in_now,
                    banish_day=banish_today, banish_recovery=banish_recov,
                    serum_choice=serum_choice,
                )
                is_sel = d == selected
                is_today = d == today_real
                am_done = bool(st.session_state.done.get(f"{k}-am"))
                pm_done = bool(st.session_state.done.get(f"{k}-pm"))

                anchor_classes = ["cell-anchor", f"is-{r['color']}"]
                if is_sel:
                    anchor_classes.append("is-selected")
                if is_today:
                    anchor_classes.append("is-today")
                st.markdown(
                    f"<span class='{' '.join(anchor_classes)}'></span>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    build_day_card_html(
                        d=d,
                        label=r["label"],
                        color=r["color"],
                        is_selected=is_sel,
                        is_today=is_today,
                        am_done=am_done,
                        pm_done=pm_done,
                        shaving=shaving,
                        banish=banish_today,
                        banish_recovery=banish_recov,
                    ),
                    unsafe_allow_html=True,
                )

                if st.button(str(d.day), key=f"day-{k}", use_container_width=True):
                    st.session_state.selected_date = d
                    st.rerun()


def render_today_panel(ls: LocalStorage) -> None:
    selected = st.session_state.selected_date
    k = date_key(selected)
    shaving = bool(st.session_state.shave_days.get(k))
    outdoor = bool(st.session_state.get("outdoor_days", {}).get(k))
    breakout = bool(st.session_state.get("breakout_week"))
    pha_opt_in = bool(st.session_state.get("pha_opt_in"))
    banish_enabled = bool(st.session_state.get("banish_enabled"))
    banish_map = st.session_state.get("banish_days", {}) if banish_enabled else {}
    recovery_days_n = int(st.session_state.get("banish_recovery_days", BANISH_DEFAULT_RECOVERY_DAYS))
    serum_choice = str(st.session_state.get("banish_serum_choice", BANISH_DEFAULT_SERUM))
    banish_today = is_banish_day(selected, banish_map)
    banish_recov = banish_recovery_offset(selected, banish_map, recovery_days_n)
    r = routine_for(selected, shaving, outdoor=outdoor,
                    breakout_week=breakout, pha_opt_in=pha_opt_in,
                    banish_day=banish_today, banish_recovery=banish_recov,
                    serum_choice=serum_choice)
    tint, ink, _accent = PILL_COLORS[r["color"]]
    _teal_tint, teal_ink, _teal_accent = PILL_COLORS["teal"]

    # ---- Day navigation strip (prev / label / next) ----
    nav = st.columns([1, 4, 1], gap="small")
    with nav[0]:
        if st.button("‹", key="prev-day",
                     disabled=selected <= START_DATE,
                     use_container_width=True):
            new_d = selected - timedelta(days=1)
            st.session_state.selected_date = new_d
            st.session_state.month = new_d.month
            st.rerun()
    with nav[1]:
        rel = ""
        today_real = date.today()
        if selected == today_real:
            rel = "Today"
        elif selected == today_real - timedelta(days=1):
            rel = "Yesterday"
        elif selected == today_real + timedelta(days=1):
            rel = "Tomorrow"
        rel_html = f"<span class='day-nav-rel'>{rel}</span>" if rel else ""
        st.markdown(
            f"<div class='day-nav-label'>"
            f"<span class='day-nav-date'>{DAY_NAMES_SHORT[selected.weekday()]} · "
            f"{MONTH_NAMES[selected.month - 1][:3]} {selected.day}</span>{rel_html}"
            "</div>",
            unsafe_allow_html=True,
        )
    with nav[2]:
        if st.button("›", key="next-day",
                     disabled=selected >= END_DATE,
                     use_container_width=True):
            new_d = selected + timedelta(days=1)
            st.session_state.selected_date = new_d
            st.session_state.month = new_d.month
            st.rerun()

    # Hero — meta, title, meaning. Shave toggle rendered below as a Streamlit
    # button styled to match the spec's outline pill.
    st.markdown(
        f"""
        <div class="hero" style="background:{tint};color:{ink};">
            <div class="h-meta">{DAY_NAMES_SHORT[selected.weekday()]} · {MONTH_NAMES[selected.month - 1][:3].upper()} {selected.day}</div>
            <div class="h-title">{r['label']} Day</div>
            <div class="h-meaning">{r['simple_meaning']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    # Anchor the next stButton so we can style it as the outline shave pill.
    pill_class = "shave-pill-active" if shaving else "shave-pill-idle"
    st.markdown(
        f"<span class='shave-pill-anchor {pill_class}'></span>",
        unsafe_allow_html=True,
    )
    if st.button(
        "✂  Shaving day" if shaving else "✂  Mark shaving day",
        key="shave-toggle",
        use_container_width=True,
    ):
        if shaving:
            st.session_state.shave_days.pop(k, None)
            st.toast("Shaving day removed")
        else:
            st.session_state.shave_days[k] = True
            st.toast("Marked as shaving day")
        save_shave(ls)
        st.rerun()

    # Outdoor / sweat day toggle — swaps BOJ for water-resistant SPF
    if st.button(
        "☀  Outdoor / sweat day" if outdoor else "☀  Mark outdoor / sweat day",
        key="outdoor-toggle",
        use_container_width=True,
    ):
        outdoor_map = st.session_state.get("outdoor_days", {})
        if outdoor:
            outdoor_map.pop(k, None)
            st.toast("Outdoor day removed")
        else:
            outdoor_map[k] = True
            st.toast("Outdoor SPF reminder set")
        st.session_state.outdoor_days = outdoor_map
        save_outdoor(ls)
        st.rerun()

    st.markdown(
        "<div class='label-tiny' style='margin-top:14px;'>Banish Kit 3.0</div>",
        unsafe_allow_html=True,
    )
    if not banish_enabled:
        st.markdown(
            "<div class='warn-rail' style='margin-top:6px;border-left-color:#2563eb;'>"
            "Banish is currently off. Turn it on here to show stamp nights and recovery days on the calendar."
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button(
            "⚠  Enable Banish kit",
            key="banish-enable-inline",
            use_container_width=True,
        ):
            st.session_state.banish_enabled = True
            save_banish(ls)
            st.toast("Banish enabled")
            st.rerun()
    else:
        serum_labels = {
            "althea": "Dr. Althea",
            "banish": "Banish serum",
            "other-gentle": "Other gentle vitamin C",
            "l-aa": "L-ascorbic acid",
            "none": "No vitamin C",
        }
        st.markdown(
            f"<div style='font-size:12px;color:#1e3a8a;background:#eff6ff;border:1px solid #bfdbfe;"
            f"border-radius:14px;padding:10px 12px;margin-top:6px;'>"
            f"<strong>ON</strong> · {str(st.session_state.get('banish_cadence', BANISH_DEFAULT_CADENCE)).title()} cadence"
            f" · {recovery_days_n} recovery day{'s' if recovery_days_n != 1 else ''}"
            f" · Serum: {serum_labels.get(serum_choice, 'Dr. Althea')}"
            f"</div>",
            unsafe_allow_html=True,
        )
        if selected < date.today():
            st.markdown(
                "<div class='warn-rail' style='margin-top:6px;'>"
                "Banish nights can only be scheduled on today or future dates."
                "</div>",
                unsafe_allow_html=True,
            )

    # ---- Banish-day toggle (only if Banish kit is enabled in sidebar) ----
    if banish_enabled and not shaving and not banish_recov and selected >= date.today():
        if st.button(
            "⚠  Banish night scheduled" if banish_today else "⚠  Schedule Banish night",
            key="banish-toggle",
            use_container_width=True,
        ):
            bmap = st.session_state.get("banish_days", {})
            if banish_today:
                bmap.pop(k, None)
                st.toast("Banish night removed")
            else:
                tomorrow_shave = st.session_state.shave_days.get(date_key(selected + timedelta(days=1)))
                if tomorrow_shave:
                    st.toast("Cannot stamp the night before a shave — pick another date")
                else:
                    bmap[k] = {"date": k, "completed": False}
                    st.toast("Banish night scheduled — 7 days SPF afterward")
            st.session_state.banish_days = bmap
            save_banish(ls)
            st.rerun()
    elif banish_enabled and shaving:
        st.markdown(
            "<div class='warn-rail' style='margin-top:6px;'>"
            "Cannot stamp on a shave day. Pick a non-shave evening with no actives planned."
            "</div>",
            unsafe_allow_html=True,
        )

    # Banish recovery banner
    if banish_recov:
        st.markdown(
            f"<div class='warn-rail' style='margin-top:10px;border-left-color:#2563eb;'>"
            f"<strong>Banish recovery — day +{banish_recov} of {recovery_days_n}.</strong> "
            f"Barrier-only routine. SPF 50+ outdoors mandatory for 7 days post-stamp."
            f"</div>",
            unsafe_allow_html=True,
        )

    # Tomorrow-Banish nudge: if tomorrow is a banish-day, no actives tonight
    if banish_enabled and r['kind'] in ("normal", "breakout") and selected < END_DATE:
        tomorrow_k = date_key(selected + timedelta(days=1))
        if banish_map.get(tomorrow_k):
            st.markdown(
                "<div class='warn-rail' style='margin-top:10px;border-left-color:#dc2626;'>"
                "<strong>Banish night tomorrow.</strong> Skip tonight's actives — "
                "the skin should be calm and barrier-intact before stamping."
                "</div>",
                unsafe_allow_html=True,
            )

    # Shave-tomorrow nudge: skip retinal/PHA tonight if shaving tomorrow
    if r['label'] in ("Retinal", "PHA (opt-in)"):
        tomorrow_key = date_key(selected + timedelta(days=1))
        if st.session_state.shave_days.get(tomorrow_key):
            st.markdown(
                "<div class='warn-rail' style='margin-top:10px;border-left-color:#dc2626;'>"
                "<strong>Shaving tomorrow.</strong> Skip tonight's actives — "
                "swap to a recovery night to protect the barrier."
                "</div>",
                unsafe_allow_html=True,
            )

    st.markdown(
        f"<div style='margin-top:14px;'>{build_warning_html(r['warning'])}</div>",
        unsafe_allow_html=True,
    )

    # ---- Tabbed AM / PM surface ----
    am_done = bool(st.session_state.done.get(f"{k}-am"))
    pm_done = bool(st.session_state.done.get(f"{k}-pm"))
    slot = st.session_state.get("active_slot", "am")

    is_am = slot == "am"
    steps = r["am"] if is_am else r["pm"]
    slot_done = am_done if is_am else pm_done

    st.markdown("<div class='routine-surface'>", unsafe_allow_html=True)

    # Real tab buttons
    tab_cols = st.columns(2, gap="small")
    am_label = f"Morning{'  ✓' if am_done else ''}"
    pm_label = f"Night{'  ✓' if pm_done else ''}"
    with tab_cols[0]:
        if st.button(am_label, key="tab-am", use_container_width=True,
                     type="primary" if is_am else "secondary"):
            st.session_state.active_slot = "am"
            st.rerun()
    with tab_cols[1]:
        if st.button(pm_label, key="tab-pm", use_container_width=True,
                     type="primary" if not is_am else "secondary"):
            st.session_state.active_slot = "pm"
            st.rerun()

    # Step list
    st.markdown(
        build_routine_surface_html(
            steps=steps, active_slot=slot,
            am_done=am_done, pm_done=pm_done, slot_done=slot_done,
        ),
        unsafe_allow_html=True,
    )

    # Real CTA
    if slot_done:
        btn_label = "✓ Morning done" if is_am else "✓ Night done"
    else:
        btn_label = "Mark morning complete" if is_am else "Mark night complete"
    if st.button(btn_label, key=f"complete-{slot}", use_container_width=True,
                 type="primary" if slot_done else "secondary"):
        slot_key = f"{k}-{slot}"
        if slot_done:
            st.session_state.done.pop(slot_key, None)
            st.toast(f"{'Morning' if is_am else 'Night'} unchecked")
        else:
            st.session_state.done[slot_key] = True
            st.toast(f"{'Morning' if is_am else 'Night'} logged ✓")
        save_done(ls)
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Tomorrow preview ----
    if selected < END_DATE:
        tomorrow = selected + timedelta(days=1)
        t_shaving = bool(st.session_state.shave_days.get(date_key(tomorrow)))
        t_outdoor = bool(st.session_state.get("outdoor_days", {}).get(date_key(tomorrow)))
        t_banish = is_banish_day(tomorrow, banish_map)
        t_recov = banish_recovery_offset(tomorrow, banish_map, recovery_days_n)
        t_r = routine_for(tomorrow, t_shaving, outdoor=t_outdoor,
                          breakout_week=breakout,
                          banish_day=t_banish, banish_recovery=t_recov,
                          serum_choice=serum_choice)
        _t_tint, _t_ink, t_accent = PILL_COLORS[t_r["color"]]
        t_rel = "Tomorrow"
        if tomorrow == date.today():
            t_rel = "Today"
        st.markdown(
            f"""
            <div class="tomorrow-preview">
                <span class="tomorrow-pip" style="background:{t_accent}"></span>
                <div class="tomorrow-text">
                    <span class="tomorrow-label">{t_rel}</span>
                    <span class="tomorrow-name">{html.escape(t_r['label'])}</span>
                </div>
                <span class="tomorrow-arrow">›</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_sidebar(ls: LocalStorage) -> None:
    with st.sidebar:
        st.markdown("<div class='label-tiny'>Routines</div>", unsafe_allow_html=True)
        st.markdown(build_legend_html(ROUTINE_LEGEND), unsafe_allow_html=True)

        st.markdown("<div class='label-tiny' style='margin-top:18px;'>Products</div>",
                    unsafe_allow_html=True)
        prod_html = "".join(f"<div class='product-row'>{p}</div>" for p in PRODUCTS)
        st.markdown(prod_html, unsafe_allow_html=True)

        # ---- Rule of thumb (one card; pager dots) ----
        tips = [
            ("Shave day = recovery day",
             "Skip retinal, azelaic, Anua, PHA, and vitamin C on freshly shaved skin tonight."),
            ("Outdoor sun",
             "Use a water-resistant SPF50+ outdoors and reapply every 2 hours. Toggle outdoor day in the today panel."),
            ("Shaving technique",
             "With the grain. Light pressure. No skin stretching. One pass when possible — closer is not better."),
            ("Rotation",
             "Retinal Mon/Fri · Azelaic Wed/Sun · Anua Thu · Recovery Tue/Sat. PHA only on calm Saturdays."),
            ("One active per night",
             "Never stack retinal, azelaic, Anua, or PHA on the same night."),
            ("Patch test",
             "New product? Patch test 7–10 days on inner forearm before going on the face."),
        ]
        tip_idx = st.session_state.get("tip_idx", 0) % len(tips)
        st.markdown(
            "<div class='label-tiny' style='margin-top:18px;'>Rule of thumb</div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"<span class='tip-dot-shell active-tip-{tip_idx}'></span>",
                    unsafe_allow_html=True)
        dot_cols = st.columns([3] + [1] * len(tips))
        for i in range(len(tips)):
            with dot_cols[i + 1]:
                if st.button("●" if i == tip_idx else "○",
                             key=f"tip-dot-{i}", use_container_width=True):
                    st.session_state.tip_idx = i
                    st.rerun()
        title, body = tips[tip_idx]
        st.markdown(build_tip_card_html(title, body), unsafe_allow_html=True)

        # ---- Breakout week toggle ----
        st.markdown("<div class='label-tiny' style='margin-top:18px;'>This week</div>",
                    unsafe_allow_html=True)
        breakout_now = bool(st.session_state.get("breakout_week"))
        if st.button(
            "✖  Breakout week active" if breakout_now else "⚠  Mark breakout week",
            key="breakout-toggle", use_container_width=True,
        ):
            st.session_state.breakout_week = not breakout_now
            save_breakout(ls)
            st.toast("Breakout week off" if breakout_now else "Breakout week on — PHA disabled")
            st.rerun()
        if breakout_now:
            st.markdown(
                "<div class='warn-rail' style='margin-top:6px;'>PHA disabled. "
                "Saturday → recovery. Sunday → azelaic.</div>",
                unsafe_allow_html=True,
            )

        # ---- PHA opt-in (Saturday only) ----
        if not breakout_now:
            pha_now = bool(st.session_state.get("pha_opt_in"))
            if st.button(
                "PHA Saturday: ON" if pha_now else "PHA Saturday: OFF (default)",
                key="pha-toggle", use_container_width=True,
            ):
                st.session_state.pha_opt_in = not pha_now
                st.toast("PHA Saturday enabled" if not pha_now else "PHA Saturday disabled")
                st.rerun()

        # ---- Banish Kit 3.0 settings ----
        st.markdown(
            "<div class='label-tiny' style='margin-top:18px;'>Banish Kit 3.0 microneedling</div>",
            unsafe_allow_html=True,
        )
        banish_on = bool(st.session_state.get("banish_enabled"))
        if st.button(
            "Banish kit: ON" if banish_on else "Banish kit: OFF (default)",
            key="banish-enabled-toggle", use_container_width=True,
        ):
            st.session_state.banish_enabled = not banish_on
            save_banish(ls)
            st.toast("Banish enabled — schedule a night on a calendar day"
                     if not banish_on else "Banish disabled")
            st.rerun()

        if banish_on:
            cadence_options = ["weekly", "biweekly", "monthly"]
            current_cadence = st.session_state.get("banish_cadence", BANISH_DEFAULT_CADENCE)
            if current_cadence not in cadence_options:
                current_cadence = BANISH_DEFAULT_CADENCE
            new_cadence = st.selectbox(
                "Cadence",
                options=cadence_options,
                index=cadence_options.index(current_cadence),
                key="banish-cadence-select",
                help="Suggested spacing between sessions. Biweekly is the safe default.",
            )
            if new_cadence != current_cadence:
                st.session_state.banish_cadence = new_cadence
                save_banish(ls)

            current_recov = int(st.session_state.get("banish_recovery_days", BANISH_DEFAULT_RECOVERY_DAYS))
            new_recov = st.slider(
                "Recovery days after stamp",
                min_value=1, max_value=4,
                value=max(1, min(4, current_recov)),
                key="banish-recovery-slider",
                help="Days of barrier-only routine following each session. 2 is standard.",
            )
            if new_recov != current_recov:
                st.session_state.banish_recovery_days = int(new_recov)
                save_banish(ls)

            serum_options = [
                ("althea", "Dr. Althea Vit C Boosting (gentle, default)"),
                ("banish", "Banish Vitamin C Serum"),
                ("other-gentle", "Other gentle vit C derivative"),
                ("l-aa", "L-ascorbic acid (skip on banish nights)"),
                ("none", "No vitamin C"),
            ]
            current_serum = st.session_state.get("banish_serum_choice", BANISH_DEFAULT_SERUM)
            serum_keys = [opt[0] for opt in serum_options]
            if current_serum not in serum_keys:
                current_serum = BANISH_DEFAULT_SERUM
            new_serum_label = st.selectbox(
                "Serum on banish nights",
                options=[opt[1] for opt in serum_options],
                index=serum_keys.index(current_serum),
                key="banish-serum-select",
                help="What to apply right after stamping. L-AA is acidic and will sting freshly stamped skin.",
            )
            new_serum = serum_keys[[opt[1] for opt in serum_options].index(new_serum_label)]
            if new_serum != current_serum:
                st.session_state.banish_serum_choice = new_serum
                save_banish(ls)

            # Session counter + head-swap reminder
            sessions_done = sum(
                1 for v in (st.session_state.get("banish_days") or {}).values()
                if isinstance(v, dict) and v.get("completed")
            )
            head_swapped = bool(st.session_state.get("banish_head_swapped"))
            sessions_since_swap = sessions_done if not head_swapped else (
                sessions_done - BANISH_HEAD_LIFETIME_SESSIONS
                if sessions_done > BANISH_HEAD_LIFETIME_SESSIONS else 0
            )
            st.markdown(
                f"<div style='font-size:12px;color:#4b5563;margin-top:6px;'>"
                f"Sessions completed: <strong>{sessions_done}</strong>"
                f"{' · head swapped' if head_swapped else ''}</div>",
                unsafe_allow_html=True,
            )
            if sessions_done >= BANISH_HEAD_LIFETIME_SESSIONS and not head_swapped:
                st.markdown(
                    "<div class='warn-rail' style='margin-top:6px;border-left-color:#dc2626;'>"
                    "<strong>Swap your Banisher head.</strong> The needles dull after "
                    f"{BANISH_HEAD_LIFETIME_SESSIONS} sessions — keep going on a dull head and you "
                    "tear instead of channel.</div>",
                    unsafe_allow_html=True,
                )
                if st.button("Mark new head installed", key="banish-head-swap",
                             use_container_width=True):
                    st.session_state.banish_head_swapped = True
                    save_banish(ls)
                    st.toast("Head swap recorded")
                    st.rerun()

        # ---- Patch test tracker ----
        st.markdown("<div class='label-tiny' style='margin-top:18px;'>Patch test</div>",
                    unsafe_allow_html=True)
        patch = st.session_state.get("patch_test") or {}
        if patch.get("product") and patch.get("start"):
            try:
                start_d = date.fromisoformat(patch["start"])
                day_n = (date.today() - start_d).days + 1
                total = int(patch.get("days", 10))
                if day_n > total:
                    st.markdown(
                        f"<div class='warn-rail' style='border-left-color:#16a34a;'>"
                        f"<strong>{html.escape(patch['product'])}</strong> — patch test complete "
                        f"({total} days). If no reaction, introduce slowly to the face.</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<div class='warn-rail' style='border-left-color:#2563eb;'>"
                        f"<strong>Day {day_n} of {total}</strong> — "
                        f"{html.escape(patch['product'])}. Apply 2×/day to inner forearm.</div>",
                        unsafe_allow_html=True,
                    )
            except (ValueError, TypeError):
                pass
            if st.button("End patch test", key="patch-end", use_container_width=True):
                st.session_state.patch_test = {}
                save_patch(ls)
                st.rerun()
        else:
            new_product = st.text_input("New product name", key="patch-product-input",
                                        placeholder="e.g. Cancer Council SPF50+")
            if st.button("Start 10-day patch test", key="patch-start",
                         use_container_width=True, disabled=not new_product.strip()):
                st.session_state.patch_test = {
                    "product": new_product.strip(),
                    "start": date.today().isoformat(),
                    "days": 10,
                }
                save_patch(ls)
                st.toast("Patch test started")
                st.rerun()

        st.markdown("<div class='label-tiny' style='margin-top:18px;color:#b91c1c;'>Danger zone</div>",
                    unsafe_allow_html=True)
        if not st.session_state.get("confirm_reset"):
            if st.button("Reset progress", key="reset-init", use_container_width=True):
                st.session_state["confirm_reset"] = True
                st.rerun()
        else:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Yes, reset", key="reset-confirm",
                             type="primary", use_container_width=True):
                    st.session_state.done = {}
                    st.session_state.banish_days = {}
                    save_done(ls)
                    save_banish(ls)
                    st.session_state["confirm_reset"] = False
                    st.toast("Progress reset")
                    st.rerun()
            with c2:
                if st.button("Cancel", key="reset-cancel", use_container_width=True):
                    st.session_state["confirm_reset"] = False
                    st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Skincare Calendar",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_styles()

    ls = LocalStorage()

    # Hydrate from URL/localStorage first so defaults don't clobber real state.
    hydrate(ls)

    if "selected_date" not in st.session_state:
        selected, month = initial_calendar_state()
        st.session_state.selected_date = selected
        st.session_state.month = month
        st.session_state.confirm_reset = False

    render_header()
    render_intro_banner(ls)
    inject_keyboard_shortcuts()
    streak_now = compute_streak(st.session_state.done, get_today())
    render_celebration(ls, streak_now)
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    render_stats_strip(st.session_state.done)
    render_month_nav()

    cal_col, today_col = st.columns([1.5, 1], gap="large")
    with cal_col:
        render_calendar(st.session_state.month)
    with today_col:
        render_today_panel(ls)

    render_sidebar(ls)


if __name__ == "__main__":
    main()
