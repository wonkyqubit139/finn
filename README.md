# FINN — Financial Investment Agent

A mobile-first intelligence layer for an Indian-equity investor. FINN has two
modes:

- **Push:** watches a portfolio of 18 NSE-listed companies and tells you what
  changed. It ranks every exchange filing by importance, collapses routine
  paperwork, and raises alerts when a price or volume move crosses *your*
  thresholds.
- **Pull (in progress):** on-demand research on any NSE company, grounded
  only in its own filings, including a *Promise Tracker* that compares what
  management guided with what was reported.

> Status: the Push side (portfolio, filings feed, classification, priority,
> alerts, settings) is working end to end. Pull is the next milestone.

---

## Run it on a Mac (from scratch)

Tested for an Intel MacBook Air with nothing installed. Homebrew is
deliberately **not** used: since September 2026 it no longer ships prebuilt
packages for Intel Macs, so it would compile Python and Node from source.

1. **Command-line tools** (provides `git`): run `xcode-select --install` in Terminal.
2. **Python 3.13:** the "macOS 64-bit universal2 installer" from
   https://www.python.org/downloads/macos/. Afterwards run
   *Install Certificates.command* from `/Applications/Python 3.13/`.
3. **Node.js:** the LTS "macOS Installer (.pkg)" from https://nodejs.org.
4. **Set up FINN** (creates `.venv`, installs packages, builds the UI, runs the tests):
   ```bash
   cd ~/Projects/finn
   bash scripts/setup.sh
   ```
5. *(Optional)* paste a free Gemini key into `.env`
   (https://aistudio.google.com/apikey): `open -e .env`
6. **Fetch live data, then start the app:**
   ```bash
   bash scripts/refresh.sh     # filings (NSE, BSE fallback) + prices (Yahoo), ~1–2 min
   bash scripts/start.sh       # open http://localhost:8000 ; Ctrl+C to stop
   ```
   `start.sh` also prints an address for your phone on the same Wi-Fi.

**While developing the UI:** run `bash scripts/start.sh` in one Terminal and
`cd frontend && npm run dev` in another, then open http://localhost:5173.

**Tests:** `cd backend && source ../.venv/bin/activate && python -m pytest -q`.
They run offline and cover the classifier (22 real-world subject patterns),
the NSE/BSE parsers, alert maths, the NSE→BSE fallback, the snapshot
round-trip, the LLM cache, and the full refresh → database → API flow.

---

## How it works

```
NSE announcements ─┐                     ┌─ classify (rules → LLM leftovers)
BSE (fallback)    ─┼─► ingest ─► SQLite ◄┼─ priority score (deterministic)
Yahoo EOD prices  ─┘                     └─ alert rules (deterministic)
                                   │
                             FastAPI /api ──► React PWA (served by FastAPI)
```

| Piece | Where | What to know |
|---|---|---|
| Sources | `backend/finn/sources/` | `curl_cffi` mimics Chrome's TLS fingerprint, which NSE's bot protection checks. If NSE refuses two symbols in a row, the run switches to BSE. |
| Classification | `pipeline/classify.py` | Ordered regex rules over the exchange's own subject + description. Routine paperwork is matched first. Only generic subjects ("General Updates") go to the LLM, batched 25 per call. |
| Priority | `pipeline/priority.py` | A visible table: base score by category/sub-type, +8 if you watch that category. ≥70 = needs attention, ≥40 = worth a look, else routine. |
| Alerts | `pipeline/alerts.py` | Price: \|close/prev − 1\| ≥ X%. Volume: today ≥ N × mean of the previous sessions. De-duplicated, so re-runs never repeat an alert. |
| LLM | `llm.py` | One OpenAI-compatible client (Gemini/Groq/OpenRouter by config). Every response is cached by hash of (task, prompt version, model, input), and every call is logged with tokens (shown under *Alerts & data*). |
| Snapshot | `pipeline/ingest.py` | `python -m finn.cli export-snapshot` saves data to `data/snapshot.json`. A deployed server whose own fetches are blocked loads it and shows a "Cached snapshot" banner. |

### Data honesty
- Every screen says where its numbers come from. Snapshot data is always
  labelled as such.
- Test fixtures are synthetic and are used only by the test suite. The app
  never displays made-up data.

## Useful commands

```bash
python -m finn.cli refresh --days 30     # backfill a month of filings
python -m finn.cli refresh --no-prices   # filings only
python -m finn.cli export-snapshot       # for deployment fallback
```
