"""Simple Skincare Routine Calendar — Streamlit port of the React JSX app.

Run with:
    streamlit run skincare_calendar/app.py
"""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

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
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # Mon-first grid

STATE_FILE = Path(__file__).parent / "state.json"

PILL_COLORS = {
    "purple": ("#ede9fe", "#5b21b6"),
    "green":  ("#dcfce7", "#166534"),
    "pink":   ("#fce7f3", "#9d174d"),
    "orange": ("#ffedd5", "#9a3412"),
    "blue":   ("#dbeafe", "#1e40af"),
    "grey":   ("#f1f5f9", "#334155"),
    "teal":   ("#ccfbf1", "#0f766e"),
}


# ---------------------------------------------------------------------------
# Routine logic (mirrors the JSX `routineFor`)
# ---------------------------------------------------------------------------
def routine_for(d: date, is_shaving_day: bool) -> dict:
    # Python weekday(): Mon=0..Sun=6. JSX getDay(): Sun=0..Sat=6.
    # Map to JSX day index for parity with original logic.
    jsx_day = (d.weekday() + 1) % 7  # Sun=0, Mon=1, ..., Sat=6

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

    if jsx_day in (1, 5):  # Mon or Fri
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
    elif jsx_day == 2:  # Tue
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
    elif jsx_day == 3:  # Wed
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
    elif jsx_day == 4:  # Thu
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
    elif jsx_day == 0:  # Sun
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
# Persistence (replaces localStorage)
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"done": {}, "shave_days": {}}


def save_state() -> None:
    STATE_FILE.write_text(
        json.dumps(
            {"done": st.session_state.done, "shave_days": st.session_state.shave_days},
            indent=2,
        )
    )


def date_key(d: date) -> str:
    return d.isoformat()


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------
def compute_progress(done: dict) -> int:
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
    return round(completed / total * 100) if total else 0


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def render_calendar(month: int) -> None:
    """Render the month grid as a 7-column button layout."""
    cal = calendar.Calendar(firstweekday=0)  # Monday
    weeks = cal.monthdatescalendar(YEAR, month)

    # Day-of-week header
    header_cols = st.columns(7)
    for i, name in enumerate(DAY_NAMES):
        header_cols[i].markdown(
            f"<div style='text-align:center;font-size:12px;color:#6b7280;font-weight:900;'>{name}</div>",
            unsafe_allow_html=True,
        )

    selected = st.session_state.selected_date

    for week in weeks:
        cols = st.columns(7)
        for i, d in enumerate(week):
            with cols[i]:
                if d.month != month:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    continue
                in_range = START_DATE <= d <= END_DATE
                k = date_key(d)
                shaving = bool(st.session_state.shave_days.get(k))
                r = routine_for(d, shaving)
                is_sel = d == selected

                bg, fg = PILL_COLORS[r["color"]]
                am_done = st.session_state.done.get(f"{k}-am")
                pm_done = st.session_state.done.get(f"{k}-pm")
                marks = ("✓" if am_done else "·") + ("✓" if pm_done else "·")
                shave_mark = " 🪒" if shaving else ""
                sel_mark = "🔵 " if is_sel else ""

                btn_label = f"{sel_mark}{d.day}{shave_mark}\n{r['label']}\nAM/PM {marks}"

                if st.button(
                    btn_label,
                    key=f"day-{k}",
                    disabled=not in_range,
                    use_container_width=True,
                ):
                    st.session_state.selected_date = d
                    st.rerun()

                # color strip under the button
                st.markdown(
                    f"<div style='height:4px;background:{bg};border-radius:4px;margin-top:-6px;'></div>",
                    unsafe_allow_html=True,
                )


def render_today_panel() -> None:
    selected = st.session_state.selected_date
    k = date_key(selected)
    shaving = bool(st.session_state.shave_days.get(k))
    r = routine_for(selected, shaving)
    bg, fg = PILL_COLORS[r["color"]]

    st.markdown(
        f"""
        <div style='background:{bg};color:{fg};border-radius:18px;padding:18px;'>
          <div style='opacity:0.75;font-weight:800;'>
            {DAY_NAMES[selected.weekday()]}, {MONTH_NAMES[selected.month - 1]} {selected.day}
          </div>
          <h2 style='margin:4px 0 0;font-size:28px;'>{r['label']} Day</h2>
          <p style='margin-top:10px;font-weight:700;line-height:1.45;'>{r['simple_meaning']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "🪒 Shaving day selected" if shaving else "Mark this as a shaving day",
        use_container_width=True,
        type="primary" if shaving else "secondary",
    ):
        st.session_state.shave_days[k] = not shaving
        if not st.session_state.shave_days[k]:
            del st.session_state.shave_days[k]
        save_state()
        st.rerun()

    # Morning
    st.markdown("### Morning — start to finish")
    am_done = bool(st.session_state.done.get(f"{k}-am"))
    if st.button(
        "✓ Done (Morning)" if am_done else "Mark Morning Done",
        key="am-done",
        use_container_width=True,
        type="primary" if am_done else "secondary",
    ):
        st.session_state.done[f"{k}-am"] = not am_done
        if not st.session_state.done[f"{k}-am"]:
            del st.session_state.done[f"{k}-am"]
        save_state()
        st.rerun()
    for i, step in enumerate(r["am"], 1):
        st.markdown(f"{i}. {step}")

    # Night
    st.markdown("### Night — start to finish")
    pm_done = bool(st.session_state.done.get(f"{k}-pm"))
    if st.button(
        "✓ Done (Night)" if pm_done else "Mark Night Done",
        key="pm-done",
        use_container_width=True,
        type="primary" if pm_done else "secondary",
    ):
        st.session_state.done[f"{k}-pm"] = not pm_done
        if not st.session_state.done[f"{k}-pm"]:
            del st.session_state.done[f"{k}-pm"]
        save_state()
        st.rerun()
    for i, step in enumerate(r["pm"], 1):
        st.markdown(f"{i}. {step}")

    st.warning(r["warning"])


def main() -> None:
    st.set_page_config(page_title="Simple Skincare Calendar", layout="wide")

    # init state
    if "loaded" not in st.session_state:
        saved = load_state()
        st.session_state.done = saved.get("done", {})
        st.session_state.shave_days = saved.get("shave_days", {})
        st.session_state.selected_date = START_DATE
        st.session_state.month = START_DATE.month
        st.session_state.loaded = True

    # Header
    st.title("Simple Skincare Calendar")
    st.write(
        "Click a date. Follow every step from start to finish. "
        "Use the shaving button on days you shave."
    )
    st.info(
        "**Simple View:** this does not weaken your routine. It only explains the routine "
        "in clearer steps. Shaving days are different because shaving can irritate the skin, "
        "so the calendar switches that day to a calming routine."
    )

    # Progress + reset
    progress = compute_progress(st.session_state.done)
    c1, c2 = st.columns([1, 4])
    with c1:
        if st.button("Reset Progress"):
            st.session_state.done = {}
            save_state()
            st.rerun()
    with c2:
        st.progress(progress / 100, text=f"{progress}% done")

    # Month controls
    left, mid, right = st.columns([1, 3, 1])
    with left:
        if st.button("‹", disabled=st.session_state.month <= START_DATE.month):
            st.session_state.month -= 1
            st.session_state.selected_date = date(
                YEAR, st.session_state.month,
                26 if st.session_state.month == START_DATE.month else 1,
            )
            st.rerun()
    with mid:
        st.markdown(
            f"<h2 style='text-align:center;margin:0;'>{MONTH_NAMES[st.session_state.month - 1]} {YEAR}</h2>",
            unsafe_allow_html=True,
        )
    with right:
        if st.button("›", disabled=st.session_state.month >= 12):
            st.session_state.month += 1
            st.session_state.selected_date = date(YEAR, st.session_state.month, 1)
            st.rerun()

    # Two-column layout: calendar | today panel
    cal_col, today_col = st.columns([1.4, 1])
    with cal_col:
        render_calendar(st.session_state.month)
    with today_col:
        render_today_panel()

    # Simple rules
    st.markdown("---")
    r1, r2, r3 = st.columns(3)
    with r1:
        st.markdown(
            "**Sunscreen choice**\n\nUse Beauty of Joseon Aqua Fresh first. "
            "Backup: Numbuzin if acne fear matters most. SKIN1004 if watery feel matters most."
        )
    with r2:
        st.markdown(
            "**Morning rule**\n\nKeep morning light. Do not layer Purito + Snail + Vanicream "
            "unless your skin is actually dry."
        )
    with r3:
        st.markdown(
            "**Shaving rule**\n\nOn shaving days, skip strong actives. Shaving already "
            "stresses the skin, so use calming products and moisturiser only."
        )


if __name__ == "__main__":
    main()
