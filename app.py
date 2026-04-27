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

PILL_COLORS = {
    "purple": ("#ede9fe", "#5b21b6"),
    "green":  ("#dcfce7", "#166534"),
    "pink":   ("#fce7f3", "#9d174d"),
    "orange": ("#ffedd5", "#9a3412"),
    "blue":   ("#dbeafe", "#1e40af"),
    "grey":   ("#f1f5f9", "#334155"),
    "teal":   ("#ccfbf1", "#0f766e"),
}

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
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(YEAR, month)

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

                bg, _fg = PILL_COLORS[r["color"]]
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

                st.markdown(
                    f"<div style='height:4px;background:{bg};border-radius:4px;margin-top:-6px;'></div>",
                    unsafe_allow_html=True,
                )


def render_today_panel(ls: LocalStorage) -> None:
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
        if shaving:
            st.session_state.shave_days.pop(k, None)
        else:
            st.session_state.shave_days[k] = True
        save_shave(ls)
        st.rerun()

    st.markdown("### Morning — start to finish")
    am_done = bool(st.session_state.done.get(f"{k}-am"))
    if st.button(
        "✓ Done (Morning)" if am_done else "Mark Morning Done",
        key="am-done",
        use_container_width=True,
        type="primary" if am_done else "secondary",
    ):
        if am_done:
            st.session_state.done.pop(f"{k}-am", None)
        else:
            st.session_state.done[f"{k}-am"] = True
        save_done(ls)
        st.rerun()
    for i, step in enumerate(r["am"], 1):
        st.markdown(f"{i}. {step}")

    st.markdown("### Night — start to finish")
    pm_done = bool(st.session_state.done.get(f"{k}-pm"))
    if st.button(
        "✓ Done (Night)" if pm_done else "Mark Night Done",
        key="pm-done",
        use_container_width=True,
        type="primary" if pm_done else "secondary",
    ):
        if pm_done:
            st.session_state.done.pop(f"{k}-pm", None)
        else:
            st.session_state.done[f"{k}-pm"] = True
        save_done(ls)
        st.rerun()
    for i, step in enumerate(r["pm"], 1):
        st.markdown(f"{i}. {step}")

    st.warning(r["warning"])


def main() -> None:
    st.set_page_config(page_title="Simple Skincare Calendar", layout="wide")

    ls = LocalStorage()

    if "selected_date" not in st.session_state:
        st.session_state.selected_date = START_DATE
        st.session_state.month = START_DATE.month
        st.session_state.done = {}
        st.session_state.shave_days = {}

    hydrate(ls)

    st.title("Simple Skincare Calendar")
    st.write(
        "Click a date. Follow every step from start to finish. "
        "Use the shaving button on days you shave."
    )
    st.info(
        "**Simple View:** this does not weaken your routine. It only explains the routine "
        "in clearer steps. Shaving days are different because shaving can irritate the skin, "
        "so the calendar switches that day to a calming routine. Your progress is saved in "
        "this browser."
    )

    progress = compute_progress(st.session_state.done)
    c1, c2 = st.columns([1, 4])
    with c1:
        if st.button("Reset Progress"):
            st.session_state.done = {}
            save_done(ls)
            st.rerun()
    with c2:
        st.progress(progress / 100, text=f"{progress}% done")

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

    cal_col, today_col = st.columns([1.4, 1])
    with cal_col:
        render_calendar(st.session_state.month)
    with today_col:
        render_today_panel(ls)

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
