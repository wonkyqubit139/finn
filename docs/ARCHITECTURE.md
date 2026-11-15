# FINN: how it works and why

## The product idea

An investor's day is **triage first, then depth**. FINN is built around those two
moments instead of a dashboard or a chatbot:

- **Push (Feed):** "what changed since I last looked?" One ranked list per time
  window: unusual price/volume moves, then filings that need attention, then
  ones worth a look. Routine paperwork is collapsed to one line. Results and
  management changes are pre-read: the card already shows the numbers, or who
  the new CFO is.
- **Pull (Research):** a dossier on any NSE company, built only from its own
  filings. Its centrepiece is the **Promise Tracker**: each thing management
  guided on recent calls, the verbatim quote, and what was later reported.

Chat was left out on purpose: it makes the investor do the asking, and the
brief's problem is filtering.

## Architecture

```
NSE announcements ─┐                       ┌─ classify (rules → model for leftovers)
BSE (fallback)    ─┼─► ingest ─► SQLite ◄──┼─ priority (deterministic table)
Yahoo EOD prices  ─┘      │                ├─ alerts (deterministic thresholds)
                          │                └─ enrich: results table, appointee profile
NSE filings (PDF) ────────┴─► research ─► documents → results → guidance → promises → synthesis
                                                │
                                     FastAPI /api ──► React PWA (served by FastAPI)
```

One Python process (FastAPI + a background refresh thread), one SQLite file,
one static frontend: a single deployable unit.

## Core principle: the model transcribes, code calculates

LLMs are used where reading messy documents is the hard part. Everything
numeric or judgemental that can be done deterministically is done in code, so
it is exact, testable and explainable.

| Task | Who does it | Why |
|---|---|---|
| Filing category | **Rules** on NSE's own subject line; the model only sees the leftovers ("General Updates"), 25 per call | Exchange subjects are formulaic. Rules are free, instant and auditable (`classified_by` shows which rule fired) |
| Priority | **Code**: a visible score table + a boost for watched categories | "Why is this ranked first?" has a numeric answer the user can change |
| Price/volume alerts | **Code**: \|close/prev − 1\| ≥ X%; volume ≥ N× trailing mean | Pure arithmetic |
| Results numbers | **Model transcribes** the statement into a fixed JSON shape; **code** converts units, picks columns by date, computes EBITDA/QoQ/YoY/margins, runs checks | A model shouldn't do arithmetic on financials |
| Guidance | **Model extracts** claims + verbatim quote + page; **code verifies** each quote against the page text | Kills invented guidance |
| Promise scoring | **Code** (Indian FY periods, growth/margin maths, target comparison) | The verdict must be reproducible |
| Overview, bull/bear, qualitative claims | **Deep model**, but only over the computed table + verified quotes; every point must cite `D<n>:p<page>` or the table | Judgement is where a model adds value; citations keep it honest |

## The non-trivial parts

### 1. Results extraction (`analysis/results.py`)
- **Page selection:** keyword scoring finds the 3–5 pages that hold the
  statement in a 20–40 page filing. That cuts tokens by about 90%. If the PDF has
  no text layer (a scanned, signed copy), the first pages are rendered to images
  and sent to the model's vision input instead.
- **Units:** statements are in ₹ crore, lakh or million. The printed unit line
  ("Rs. in lakhs") is read by regex and **overrides** the model's reading if
  they disagree, with a note shown. Everything is normalised to ₹ crore.
- **Columns:** a results statement prints the current quarter, the previous
  quarter, the year-ago quarter, plus half-year/year columns. Code identifies
  them **by date** (current = latest quarter; previous = −1 quarter; year-ago =
  −4 quarters). It doesn't rely on column position.
- **EBITDA is reconstructed, carefully.** SEBI's results format has no EBITDA line. FINN uses
  `profit before exceptional items and tax + finance costs + D&A − other income − share of associates/JVs`.
  It **refuses** (and says why) when a component isn't printed, or when
  exceptional items exist but no pre-exceptional profit line is given. For
  banks/NBFCs it is never computed: interest is their main operating cost.
- **Checks:** `PBT − tax = net profit`, `revenue + other income = total income`
  (tolerating rounding), and across filings: a quarter reported in one filing
  must match its comparative column in the next one, otherwise a
  restatement/mis-read is flagged.

### 2. Guidance and quote verification (`analysis/guidance.py`)
The model returns each forward-looking statement with a quote and page.
`find_quote` normalises both sides (case, quotes, dashes, words hyphenated
across PDF lines) and looks for an exact match, then a fuzzy window match
(≥ 0.9). If the quote isn't in the transcript, the claim is **dropped and
counted** ("3 withheld"). The page number is corrected to where the quote
really is.

### 3. Promise Tracker (`analysis/promises.py`, `analysis/periods.py`)
- `parse_period` turns "FY27", "Q3 FY27", "H2", "next quarter", "this year"
  into concrete quarter-end dates on the **Indian financial year** (FY27 =
  Apr 2026–Mar 2027), relative to the call the statement was made on.
- Growth targets are computed as sum(reported quarters) ÷ sum(same quarters a
  year earlier). Margin targets use summed numerators/denominators (not an
  average of ratios), and "+50 bps" targets compare with the year-ago margin.
- Status: **delivered/missed** when the period is complete; **on/off track**
  when partly reported (shows which quarters); **pending** when not yet
  reported; **can't verify** for metrics absent from the statements (order
  book, AUM, volumes). Those go to the model, whose answer is labelled
  "Model's read".
- The same guidance repeated on several calls is merged into one row ("also
  said on the Q1 FY27 and Q4 FY26 calls"). Consistency is itself a signal.

### 4. Primary sources only
Documents are discovered from the **company's own NSE announcements**
(results filings, transcripts), not from news or aggregators. That's more
primary than Screener, which the brief allowed. Every number carries
(document, page), and a citation chip opens that page's extracted text next
to a link to the NSE PDF.

## Engineering efficiency

- **Caching at two levels:** `llm_cache` (hash of task + prompt version + model
  + input) and `extractions` (per document). A rebuild with no new filings
  makes **zero** model calls (tested). Bumping a prompt version invalidates
  only that task.
- **Model tiers:** a fast/cheap model for bulk transcription and
  classification, a stronger one only for guidance and synthesis. Both are
  config, not code (any OpenAI-compatible endpoint).
- **Batching:** classification leftovers go 25 per call.
- **Bounded work:** feed enrichment is capped per refresh. Research builds
  run one at a time (free-tier rate limits), with an hourly cap on public deployments.
- **Usage visible:** every call is logged with tokens. *Alerts & data* and
  each dossier show calls, cache hits and tokens.

## Failure handling

- **Sources:** NSE is tried first. Two refusals switch the run to BSE, and if both fail it
  stops early instead of timing out 18 times. `curl_cffi` uses a Chrome TLS fingerprint,
  which NSE's bot protection checks.
- **Blocked servers:** `export-snapshot` ships filings, prices, dossiers,
  page text and cached model answers. An empty deployed database loads it and
  the UI says "Cached snapshot".
- **Model problems:** 429/5xx retries honour Retry-After; invalid JSON gets one
  repair attempt; failures never crash a refresh. The model call is made outside
  any open database write, which was a real deadlock found on first live run. A
  regression test covers it.

## Testing

55 offline tests, no network: classifier cases from real subject patterns,
parsers, alert maths, results maths with hand-checked answers (lakh → crore,
EBITDA refusal, banks, restatements), period parsing, quote verification
(hyphenated PDF text, invented quotes), promise scoring, citation
enforcement, snapshot round-trip, and **full end-to-end builds** where a fake
exchange serves real generated PDFs and a fake model answers like Gemini
(including an invented quote and uncited points that must be removed).

## Known limits / next steps

- Annual reports aren't used yet (multi-year trend is limited to what the
  last 4 results filings and the latest Q4 filing contain). Next: targeted
  page search in the AR (MD&A, segment note, contingent liabilities).
- Balance sheet and cash flow: the Q2/Q4 results filings contain them; the
  same transcribe-then-compute pattern applies. Not built yet.
- Operational KPIs (AUM, order book, volumes) live in investor presentations.
  Extracting them would let more guidance be scored in code.
- Real phone push notifications (alerts are an in-app inbox today).
