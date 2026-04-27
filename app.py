"""Simple Skincare Routine Calendar — Streamlit app with browser-persistent state.

State (completed AM/PM and shaving days) lives in the user's browser via
localStorage, so each visitor keeps their own progress across sessions —
even on Streamlit Community Cloud where the server filesystem is ephemeral.

Run locally:
    streamlit run app.py
"""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta

import streamlit as st
from streamlit_local_storage import LocalStorage

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
    ("purple", "Retinal", "Mon · Fri"),
    ("blue", "Optional Toner", "Tue"),
    ("green", "Azelaic Acid", "Wed"),
    ("pink", "Anua", "Thu"),
    ("grey", "Recovery", "Sat"),
    ("orange", "Choose One", "Sun"),
    ("teal", "Shaving", "Any marked day"),
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


# ---------------------------------------------------------------------------
# Routine logic (mirrors the JSX `routineFor`)
# ---------------------------------------------------------------------------
def routine_for(d: date, is_shaving_day: bool) -> dict:
    jsx_day = (d.weekday() + 1) % 7  # Sun=0..Sat=6 to match original

    label = "Recovery"
    color = "grey"
    simple_meaning = "Barrier repair night. This keeps your skin calm and less breakout-prone."
    warning = "No strong actives tonight. Recovery nights are what stop irritation from building up."

    am = [
        "Cleanse or rinse with water",
        "Apply Dr. Althea Gentle Vitamin C Serum",
        "Apply ONE calming layer: Purito Centella OR COSRX Snail Mucin",
        "Apply a tiny amount of Vanicream only if your skin feels dry",
        "Apply sunscreen as the final step",
    ]
    pm = [
        "Cleanse",
        "Apply COSRX Snail Mucin",
        "Apply Purito Centella Serum",
        "Seal with Vanicream Ceramide Moisturiser",
    ]

    if jsx_day in (1, 5):
        label = "Retinal"
        color = "purple"
        simple_meaning = "Anti-ageing, texture, pores, and glow night."
        warning = "Do not use Anua, azelaic acid, or SKIN1004 toner tonight."
        pm = [
            "Cleanse and dry your face fully",
            "Apply Purito Centella OR COSRX Snail Mucin if your skin feels sensitive",
            "Apply Medik8 Retinal 6, pea-size amount for the whole face",
            "Seal with Vanicream Ceramide Moisturiser",
        ]
    elif jsx_day == 2:
        label = "Optional Toner"
        color = "blue"
        simple_meaning = "Very gentle exfoliation night. Only do this if your skin feels calm."
        warning = "Skip the SKIN1004 toner if your skin is dry, tight, red, peeling, freshly shaved, or bumpy."
        pm = [
            "Cleanse",
            "Apply SKIN1004 Toner only if your skin is calm",
            "Apply COSRX Snail Mucin",
            "Seal with Vanicream Ceramide Moisturiser",
        ]
    elif jsx_day == 3:
        label = "Azelaic Acid"
        color = "green"
        simple_meaning = "Acne, redness, bumps, and post-acne mark night."
        warning = "Do not use retinal, Anua, or SKIN1004 toner tonight."
        pm = [
            "Cleanse and pat dry",
            "Apply Cos De BAHA Azelaic Acid 10% Serum",
            "Apply Purito Centella OR COSRX Snail Mucin",
            "Seal with Vanicream Ceramide Moisturiser",
        ]
    elif jsx_day == 4:
        label = "Anua"
        color = "pink"
        simple_meaning = "Pigmentation, uneven tone, and brightening night."
        warning = "Do not use retinal, azelaic acid, or SKIN1004 toner tonight."
        pm = [
            "Cleanse",
            "Apply Anua Niacinamide 10% + TXA 4% Serum",
            "Apply Purito Centella OR COSRX Snail Mucin",
            "Seal with Vanicream Ceramide Moisturiser",
        ]
    elif jsx_day == 0:
        label = "Choose One"
        color = "orange"
        simple_meaning = "Flexible treatment night. Pick based on what your skin needs most."
        warning = "Choose only one active: Anua OR azelaic acid. Never both on the same night."
        pm = [
            "Cleanse",
            "Choose ONE: Anua if pigmentation is the issue OR azelaic acid if acne/redness is the issue",
            "Apply Purito Centella OR COSRX Snail Mucin",
            "Seal with Vanicream Ceramide Moisturiser",
        ]

    if is_shaving_day:
        label = "Shaving"
        color = "teal"
        simple_meaning = (
            "Shaving day. Keep the routine calm so you do not trigger razor bumps, "
            "irritation, or clogged-feeling skin."
        )
        warning = (
            "After shaving, skip retinal, azelaic acid, Anua, SKIN1004 toner, "
            "and vitamin C on shaved areas for that routine."
        )
        am = [
            "Cleanse or soften skin with warm water",
            "Shave gently with a clean razor and shaving gel/cream",
            "Rinse with cool water and pat dry",
            "Apply Purito Centella OR COSRX Snail Mucin",
            "Apply a tiny amount of Vanicream if skin feels dry or tight",
            "Apply sunscreen as the final step",
        ]
        pm = [
            "Cleanse gently",
            "If you shave at night: shave now, then rinse and pat dry",
            "Apply Purito Centella OR COSRX Snail Mucin",
            "Apply Vanicream Ceramide Moisturiser",
            "No actives tonight",
        ]

    return {
        "am": am,
        "pm": pm,
        "label": label,
        "color": color,
        "simple_meaning": simple_meaning,
        "warning": warning,
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


def hydrate(ls: LocalStorage) -> None:
    if st.session_state.get("_hydrated"):
        return
    st.session_state.done = _parse(ls.getItem(LS_DONE_KEY))
    st.session_state.shave_days = _parse(ls.getItem(LS_SHAVE_KEY))
    st.session_state._hydrated = True


def save_done(ls: LocalStorage) -> None:
    ls.setItem(LS_DONE_KEY, json.dumps(st.session_state.done), key="ls-set-done")


def save_shave(ls: LocalStorage) -> None:
    ls.setItem(LS_SHAVE_KEY, json.dumps(st.session_state.shave_days), key="ls-set-shave")


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


# ---------------------------------------------------------------------------
# Global styles
# ---------------------------------------------------------------------------
def inject_styles() -> None:
    css_rules = []
    for name, (tint, ink, accent) in PILL_COLORS.items():
        css_rules.append(
            f"""
            div[data-testid="stColumn"]:has(.cell-anchor.is-{name}) div.stButton > button {{
                background: {tint};
                color: {ink};
                border: 1px solid {accent}55;
            }}
            div[data-testid="stColumn"]:has(.cell-anchor.is-{name}) div.stButton > button:hover {{
                background: {tint};
                border-color: {accent};
                color: {ink};
            }}
            div[data-testid="stColumn"]:has(.cell-anchor.is-{name}.is-selected) div.stButton > button {{
                background: {ink};
                color: #ffffff;
                border-color: {ink};
            }}
            """
        )
    color_rules = "\n".join(css_rules)

    style_block = f"""
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
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
        h1, h2, h3, h4 {{ font-family: 'Inter', system-ui, sans-serif; font-weight: 700; letter-spacing: -0.01em; }}
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
                   box-shadow: 0 1px 0 rgba(0,0,0,0.03), 0 1px 2px rgba(0,0,0,0.04); }}
        .metric .m-label {{ font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
                            text-transform: uppercase; color: #6b7280; }}
        .metric .m-value {{ font-size: 28px; font-weight: 800; color: #111111; margin-top: 4px;
                            line-height: 1.1; font-variant-numeric: tabular-nums; }}
        .metric .m-cap {{ font-size: 12px; color: #9ca3af; margin-top: 2px; }}

        /* ---------- Slim progress bar ---------- */
        .slim-track {{ height: 6px; background: #f3f4f6; border-radius: 999px; overflow: hidden; }}
        .slim-fill {{ height: 100%; background: #111111; border-radius: 999px; }}

        /* ---------- Calendar grid ---------- */
        .cell-anchor {{ display: none; }}

        div[data-testid="stColumn"]:has(.cell-anchor) div.stButton > button {{
            height: 88px !important;
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
        div[data-testid="stColumn"]:has(.cell-anchor) div.stButton > button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        div[data-testid="stColumn"]:has(.cell-anchor.is-today) div.stButton > button {{
            outline: 2px solid #111111;
            outline-offset: 2px;
        }}
        div[data-testid="stColumn"]:has(.cell-anchor.is-selected) div.stButton > button {{
            transform: scale(1.02);
            box-shadow: 0 8px 24px rgba(0,0,0,0.10);
        }}
        div[data-testid="stColumn"]:has(.cell-anchor.is-empty) div.stButton {{ visibility: hidden; }}
        div[data-testid="stColumn"]:has(.cell-anchor.is-disabled) div.stButton > button {{
            background: #fafafa !important;
            color: #9ca3af !important;
            border: 1px dashed #e5e7eb !important;
            box-shadow: none !important;
            cursor: not-allowed !important;
            transform: none !important;
        }}

        .cell-wrap {{ position: relative; }}
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
        div[data-testid="stColumn"]:has(.cell-anchor.is-selected) .cell-overlay {{ color: #ffffff !important; }}
        div[data-testid="stColumn"]:has(.cell-anchor.is-selected) .cell-shave {{ color: #ffffff !important; }}

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
            background: #fef7d6; color: #6b4f00; border-radius: 12px;
            padding: 12px 14px; display: flex; gap: 10px; align-items: flex-start;
            font-size: 13px; font-weight: 500; line-height: 1.5;
        }}
        .warn .warn-icon {{ font-weight: 800; font-size: 16px; }}

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
        .step-row {{
            display: flex; align-items: flex-start; gap: 12px;
            padding: 10px 0; border-bottom: 1px solid #e5e7eb;
            font-size: 14px; color: #1f2937;
        }}
        .step-row:last-child {{ border-bottom: none; }}
        .step-num {{
            width: 22px; height: 22px; border-radius: 50%; background: #f3f4f6;
            color: #4b5563; font-size: 12px; font-weight: 700;
            display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
        }}

        /* ---------- Sidebar ---------- */
        [data-testid="stSidebar"] {{ background: #ffffff !important; border-right: 1px solid #e5e7eb; }}
        [data-testid="stSidebar"] .block-container {{ padding-top: 1.5rem; }}
        .legend-row {{ display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 13px; }}
        .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }}
        .legend-name {{ font-weight: 600; color: #111111; flex: 1; }}
        .legend-when {{ color: #9ca3af; font-size: 12px; }}
        .product-row {{
            font-size: 13px; padding: 6px 0; color: #1f2937;
            border-bottom: 1px solid #e5e7eb;
        }}
        .product-row:last-child {{ border-bottom: none; }}
        .tip-card {{
            background: #f9fafb; border-radius: 10px; padding: 10px 12px;
            font-size: 12px; color: #4b5563; line-height: 1.5; margin-bottom: 8px;
        }}
        .tip-card strong {{ color: #111111; }}

        /* ---------- Buttons ---------- */
        div.stButton > button {{
            font-family: 'Inter', sans-serif !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            transition: all 160ms ease;
        }}
        div.stButton > button:hover {{ transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.06); }}

        /* ---------- Reduced motion ---------- */
        @media (prefers-reduced-motion: reduce) {{
            * {{ transition: none !important; transform: none !important; }}
        }}

        /* ---------- Mobile ---------- */
        @media (max-width: 720px) {{
            div[data-testid="stColumn"]:has(.cell-anchor) div.stButton > button {{
                height: 64px !important; font-size: 14px !important;
            }}
            .cell-label {{ display: none; }}
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


def render_stats_strip(done: dict) -> None:
    today = get_today()
    streak = compute_streak(done, today)
    week_done, week_total = compute_week_progress(done, today)
    pct, _completed, total = compute_progress(done)
    days_total = total // 2

    cols = st.columns(3)
    cards = [
        ("Streak", f"{streak} {'day' if streak == 1 else 'days'}", "consecutive AM + PM"),
        ("This week", f"{week_done} / {week_total}" if week_total else "—",
         "morning + night this week"),
        ("Overall", f"{pct}%", f"{days_total} days total"),
    ]
    for col, (lbl, val, cap) in zip(cols, cards):
        with col:
            st.markdown(
                f"""
                <div class="metric">
                    <div class="m-label">{lbl}</div>
                    <div class="m-value">{val}</div>
                    <div class="m-cap">{cap}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        f"""
        <div style="margin-top:10px;">
            <div class="slim-track"><div class="slim-fill" style="width:{pct}%"></div></div>
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
                    st.markdown("<span class='cell-anchor is-empty'></span>",
                                unsafe_allow_html=True)
                    st.button(" ", key=f"empty-{w_idx}-{i}", disabled=True,
                              use_container_width=True)
                    continue
                if not in_range:
                    # In-month but out of program window: calm dashed tile
                    st.markdown("<span class='cell-anchor is-disabled'></span>",
                                unsafe_allow_html=True)
                    st.button(str(d.day), key=f"oor-{w_idx}-{i}", disabled=True,
                              use_container_width=True)
                    continue

                k = date_key(d)
                shaving = bool(st.session_state.shave_days.get(k))
                r = routine_for(d, shaving)
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

                st.markdown("<div class='cell-wrap'>", unsafe_allow_html=True)

                if st.button(str(d.day), key=f"day-{k}", use_container_width=True):
                    st.session_state.selected_date = d
                    st.rerun()

                shave_glyph = "<div class='cell-shave'>✂</div>" if shaving else "<div></div>"
                am_cls = "cell-dot filled" if am_done else "cell-dot"
                pm_cls = "cell-dot filled" if pm_done else "cell-dot"
                st.markdown(
                    f"""
                    <div class='cell-overlay'>
                        <div class='cell-top'><div></div>{shave_glyph}</div>
                        <div class='cell-bot'>
                            <div class='cell-label'>{r['label']}</div>
                            <div class='cell-dots'>
                                <span class='{am_cls}'></span>
                                <span class='{pm_cls}'></span>
                            </div>
                        </div>
                    </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_today_panel(ls: LocalStorage) -> None:
    selected = st.session_state.selected_date
    k = date_key(selected)
    shaving = bool(st.session_state.shave_days.get(k))
    r = routine_for(selected, shaving)
    tint, ink, _accent = PILL_COLORS[r["color"]]
    _teal_tint, teal_ink, _teal_accent = PILL_COLORS["teal"]

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

    st.markdown(
        f"""
        <div class="warn" style="margin-top:14px;">
            <div class="warn-icon">⚠</div><div>{r['warning']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- Tabbed AM / PM surface ----
    am_done = bool(st.session_state.done.get(f"{k}-am"))
    pm_done = bool(st.session_state.done.get(f"{k}-pm"))
    slot = st.session_state.get("active_slot", "am")

    tab_cols = st.columns(2, gap="small")
    am_label = "Morning" + ("  ✓" if am_done else "")
    pm_label = "Night" + ("  ✓" if pm_done else "")
    with tab_cols[0]:
        if st.button(am_label, key="tab-am", use_container_width=True,
                     type="primary" if slot == "am" else "secondary"):
            st.session_state.active_slot = "am"
            st.rerun()
    with tab_cols[1]:
        if st.button(pm_label, key="tab-pm", use_container_width=True,
                     type="primary" if slot == "pm" else "secondary"):
            st.session_state.active_slot = "pm"
            st.rerun()

    is_am = slot == "am"
    steps = r["am"] if is_am else r["pm"]
    slot_done = am_done if is_am else pm_done
    steps_html = "".join(
        f"<div class='step-row'><span class='step-num'>{i}</span><span>{step}</span></div>"
        for i, step in enumerate(steps, 1)
    )
    st.markdown(
        f"<div class='surface-tight' style='margin-top:10px;'>{steps_html}</div>",
        unsafe_allow_html=True,
    )

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


def render_sidebar(ls: LocalStorage) -> None:
    with st.sidebar:
        st.markdown("<div class='label-tiny'>Routines</div>", unsafe_allow_html=True)
        legend_html = ""
        for color, name, when in ROUTINE_LEGEND:
            _tint, _ink, accent = PILL_COLORS[color]
            legend_html += (
                f"<div class='legend-row'>"
                f"<span class='legend-dot' style='background:{accent};'></span>"
                f"<span class='legend-name'>{name}</span>"
                f"<span class='legend-when'>{when}</span>"
                f"</div>"
            )
        st.markdown(legend_html, unsafe_allow_html=True)

        st.markdown("<div class='label-tiny' style='margin-top:18px;'>Products</div>",
                    unsafe_allow_html=True)
        prod_html = "".join(f"<div class='product-row'>{p}</div>" for p in PRODUCTS)
        st.markdown(prod_html, unsafe_allow_html=True)

        # ---- Rule of thumb (one card; pager dots) ----
        tips = [
            ("Sunscreen", "Beauty of Joseon Aqua Fresh first. Numbuzin or SKIN1004 as backup."),
            ("Morning",   "Keep it light. Don't layer Purito + Snail + Vanicream unless skin is dry."),
            ("Shaving",   "Skip actives on shaving days — calming products and moisturiser only."),
        ]
        tip_idx = st.session_state.get("tip_idx", 0) % len(tips)
        st.markdown(
            "<div class='label-tiny' style='margin-top:18px;'>Rule of thumb</div>",
            unsafe_allow_html=True,
        )
        dot_cols = st.columns([6, 1, 1, 1])
        for i in range(len(tips)):
            with dot_cols[i + 1]:
                if st.button("●" if i == tip_idx else "○",
                             key=f"tip-dot-{i}", use_container_width=True):
                    st.session_state.tip_idx = i
                    st.rerun()
        title, body = tips[tip_idx]
        st.markdown(
            f"<div class='tip-card'><strong>{title}.</strong> {body}</div>",
            unsafe_allow_html=True,
        )

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
                    save_done(ls)
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

    if "selected_date" not in st.session_state:
        st.session_state.selected_date = START_DATE
        st.session_state.month = START_DATE.month
        st.session_state.done = {}
        st.session_state.shave_days = {}
        st.session_state.confirm_reset = False

    hydrate(ls)

    render_header()
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
