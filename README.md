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

These steps assume a Mac with no developer tools installed. Commands go in
the **Terminal** app.

### 1. One-time installs (≈10 minutes)

```bash
# Apple's command-line tools (git, compilers). A dialog pops up; click Install.
xcode-select --install

# Homebrew, the Mac package manager. Follow the "Next steps" it prints at the end
# (on Intel Macs it usually needs no extra step).
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3.12 and Node.js 22
brew install python@3.12 node@22
brew link --overwrite node@22
python3.12 --version   # should print 3.12.x
node --version         # should print v22.x
```

### 2. Get the code and install dependencies

```bash
git clone https://github.com/<your-username>/finn.git
cd finn

# Python packages in an isolated virtual environment
python3.12 -m venv .venv
source .venv/bin/activate          # run this again in every new Terminal window
pip install -r backend/requirements.txt

# Frontend packages
cd frontend && npm install && cd ..
```

### 3. (Optional) add a model key

```bash
cp .env.example .env
open -e .env       # paste a free Gemini key from https://aistudio.google.com/apikey
```

Without a key everything still works; generic filings ("General Updates") just
stay unclassified instead of being read by the model.

### 4. Fetch live data and run

```bash
source .venv/bin/activate
cd backend
python -m finn.cli refresh        # pulls filings (NSE, BSE fallback) + prices (Yahoo); ~1–2 min
python -m finn.cli sources        # shows which sources succeeded

cd ../frontend && npm run build && cd ../backend
uvicorn finn.api:app --port 8000  # open http://localhost:8000
```

To open it on your phone, connect it to the same Wi-Fi network and run
`uvicorn finn.api:app --host 0.0.0.0 --port 8000`. Then open
`http://<your-mac's-IP>:8000` on the phone (System Settings → Wi-Fi → Details
shows the IP).

**While developing the UI**, run the backend with
`uvicorn finn.api:app --reload --port 8000`, and in a second Terminal run
`cd frontend && npm run dev`. Then open http://localhost:5173. Changes appear
instantly.

### 5. Tests

```bash
cd backend && python -m pytest -q
```

The tests run offline. They cover the classifier (22 real-world subject
patterns), the NSE/BSE parsers, alert arithmetic, the NSE→BSE fallback, the
snapshot round-trip and the full refresh → database → API flow.

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
