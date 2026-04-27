# Simple Skincare Calendar (Streamlit)

Streamlit port of the React skincare routine calendar.

## Run

```bash
pip install streamlit
streamlit run skincare_calendar/app.py
```

State (completed AM/PM and shaving days) is persisted to `state.json` in this folder.

## Routine map

- **Mon / Fri** — Retinal
- **Tue** — Optional Toner (SKIN1004)
- **Wed** — Azelaic Acid
- **Thu** — Anua (Niacinamide + TXA)
- **Sat** — Recovery
- **Sun** — Choose One (Anua *or* Azelaic, never both)
- **Any day marked 🪒** — Shaving routine (overrides actives)

Date range: 26 Apr 2026 → 31 Dec 2026.
