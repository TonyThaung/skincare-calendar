from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import types


def load_app():
    sys.modules.setdefault("streamlit", types.SimpleNamespace())
    sys.modules.setdefault(
        "streamlit_local_storage",
        types.SimpleNamespace(LocalStorage=object),
    )

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("skincare_app_under_test", app_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def mark_done(done: dict[str, bool], d: date, *slots: str) -> None:
    for slot in slots:
        done[f"{d.isoformat()}-{slot}"] = True


def test_deck_stats_visuals_capture_done_partial_and_ref_states():
    app = load_app()
    done: dict[str, bool] = {}
    mark_done(done, date(2026, 4, 27), "am", "pm")
    mark_done(done, date(2026, 4, 28), "am")
    mark_done(done, date(2026, 4, 29), "pm")

    visuals = app.build_stats_visuals(done, date(2026, 4, 29))

    assert visuals["streak_dots"].count("<span class='stat-dot") == 7
    assert "is-done" in visuals["streak_dots"]
    assert "is-ref" in visuals["streak_dots"]
    assert visuals["week_chips"].count("<span class='week-chip") == 7
    assert "is-partial" in visuals["week_chips"]
    assert "1%" in visuals["overall_caption"]
    assert "width:1%" in visuals["overall_bar"]


def test_warning_and_tip_html_use_deck_rail_treatments_and_escape_copy():
    app = load_app()

    warning = app.build_warning_html("Do not use <active> tonight.")
    tip = app.build_tip_card_html("Sunscreen", "Use <one> calm layer.")

    assert "warn-rail" in warning
    assert "Avoid tonight" in warning
    assert "warn-glyph" in warning
    assert "&lt;active&gt;" in warning
    assert "tip-rail" in tip
    assert "tip-glyph" in tip
    assert "&lt;one&gt;" in tip


def test_day_card_html_keeps_label_inside_selected_black_tile():
    app = load_app()

    card = app.build_day_card_html(
        d=date(2026, 4, 26),
        label="Choose <One>",
        color="orange",
        is_selected=True,
        is_today=False,
        am_done=True,
        pm_done=False,
    )

    assert "day-card is-selected" in card
    assert "background:#111111" in card
    assert "Choose &lt;One&gt;" in card
    assert card.count("<span class='cell-dot") == 2
    assert "cell-dot filled" in card


def test_calendar_spillover_uses_spacer_not_hidden_buttons():
    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text()

    assert "cell-anchor is-empty" not in app_source
    assert "cal-spacer" in app_source
    assert 'div[data-testid="stColumn"]:has(.cell-anchor' not in app_source
    assert "st-key-tab-am" in app_source
    assert "st-key-shave-toggle" in app_source


def test_initial_calendar_state_starts_on_clamped_today():
    app = load_app()

    selected, month = app.initial_calendar_state()

    assert selected == app.get_today()
    assert month == selected.month


def test_routine_surface_html_matches_prototype_card_shape():
    app = load_app()

    surface = app.build_routine_surface_html(
        steps=["Cleanse", "Apply moisturiser"],
        active_slot="am",
        am_done=True,
        pm_done=False,
        slot_done=False,
    )

    assert "routine-surface" in surface
    assert "routine-tab is-active" in surface
    assert "Morning" in surface
    assert "Night" in surface
    assert "tab-check" in surface
    assert "routine-steps surface-tight" in surface
    assert "step-row active" in surface
    assert "step-num" in surface
    assert "routine-complete-preview" in surface
    assert "Mark morning complete" in surface


def test_routine_surface_done_state_uses_preview_check_rows():
    app = load_app()

    surface = app.build_routine_surface_html(
        steps=["Cleanse", "Apply moisturiser"],
        active_slot="pm",
        am_done=False,
        pm_done=True,
        slot_done=True,
    )

    assert surface.count("step-row done") == 2
    assert "routine-complete-preview is-done" in surface
    assert "✓ Night done" in surface


def test_sidebar_legend_uses_preview_card_structure():
    app = load_app()

    legend = app.build_legend_html(app.ROUTINE_LEGEND)

    assert "legend-card" in legend
    assert legend.count("legend-item") == 6
    assert "legend-pip" in legend
    assert "legend-purpose" in legend
    assert "legend-uses" in legend
    assert "shave-tag" in legend


def test_tip_dot_buttons_are_styled_as_preview_pager_dots():
    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text()

    assert "st-key-tip-dot-0" in app_source
    assert "tip-dot-shell" in app_source
