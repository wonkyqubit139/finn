# FINN — Financial Investment Agent

**Live demo:** https://finn-production-48f5e4a8.up.railway.app (mobile-first; open on a phone)

A mobile-first intelligence layer for an Indian-equity investor. FINN has two
modes:

- **Push:** watches a portfolio of 18 NSE-listed companies and tells you what
  changed. It ranks every exchange filing by importance, collapses routine
  paperwork, and raises alerts when a price or volume move crosses *your*
  thresholds.
- **Pull:** on-demand research on any NSE company, grounded only in its own
  exchange filings (quarterly results statements and concall transcripts).
  Every figure and claim links to the page it came from. The centrepiece is
  the **Promise Tracker**: what management guided on recent calls, scored in
  code against the numbers they later reported.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how and why it works.

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
They run offline (55 tests) and cover the classifier (22 real-world subject patterns),
the NSE/BSE parsers, alert maths, the NSE→BSE fallback, the snapshot
round-trip, the LLM cache, results maths, quote verification, promise scoring, and full end-to-end feed and research builds.

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
| Research | `research/`, `analysis/` | See docs/ARCHITECTURE.md. Model transcribes, code calculates; quotes verified; citations enforced. |
| Snapshot | `pipeline/ingest.py` | `export-snapshot` saves filings, prices, dossiers, page text and cached model answers. An empty deployed DB loads it and shows a "Cached snapshot" banner. |

### Data honesty
- Every screen says where its numbers come from. Snapshot data is always
  labelled as such.
- Test fixtures are synthetic and are used only by the test suite. The app
  never displays made-up data.

## Research a company

In the app, open **Research** and type a symbol (e.g. `DIXON`). The first build
takes 1–3 minutes and shows its progress. Later views load from cache.
From the terminal:

```bash
cd backend && source ../.venv/bin/activate
python -m finn.cli research DIXON            # build and print a summary
python -m finn.cli research DIXON --force    # rebuild (cached model answers are reused)
```

## Deploy (Railway, with persistent SQLite)

Render's free tier and Hugging Face Spaces wipe the disk on restart, and Fly.io
has no free allowance for new accounts. Railway's free/trial plan includes a
0.5 GB volume, enough for FINN's database.

1. **Prepare a snapshot on your Mac.** The exchanges may block cloud servers, so
   the deployed app ships with data fetched from your machine:
   ```bash
   bash scripts/refresh.sh
   cd backend && source ../.venv/bin/activate
   python -m finn.cli research BAJFINANCE && python -m finn.cli research DIXON && python -m finn.cli research ASIANPAINT
   python -m finn.cli export-snapshot           # writes data/snapshot.json.gz
   cd .. && git add data/snapshot.json.gz && git commit -m "Data snapshot" && git push
   ```
2. On https://railway.com: **New Project → Deploy from GitHub repo →** pick your repo.
   Railway finds the `Dockerfile` and `railway.json` itself.
3. In the service: **Settings → Volumes → Add volume**, mount path `/data`.
4. **Variables:** `GEMINI_API_KEY=<your key>`, `FINN_DB=/data/finn.db`,
   `FINN_DOC_DIR=/tmp/finn-docs` (PDFs are only needed while being read, so keep
   them off the small volume).
5. **Settings → Networking → Generate domain.** Open it. On first boot the empty
   volume is filled from the snapshot. Later live refreshes, if the exchanges
   allow the server, add to it.

`FINN_MAX_BUILDS_PER_HOUR` (default 6) caps new research builds so a public link
can't exhaust your model quota. Existing dossiers are always served.

## Useful commands

```bash
python -m finn.cli refresh --days 30     # backfill a month of filings
python -m finn.cli refresh --no-prices   # filings only
python -m finn.cli export-snapshot       # data/snapshot.json.gz for deployment
```
