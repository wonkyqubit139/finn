"""Announcement classification — rules first, LLM only for what rules can't decide.

Why rules first: exchange filings are formulaic. NSE's own subject line
("Outcome of Board Meeting", "Closure of Trading Window", "Copy of Newspaper
Publication"...) plus the one-line description already pin down the category
for the large majority of filings. Regexes are free, instant, deterministic and
explainable. The LLM is reserved for generic subjects ("General Updates",
"Press Release") whose meaning is in the text.

Categories follow the ENAM reference document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation",
    "insider_trading", "earnings_call", "investor_meetings", "credit_rating",
    "dividend", "bonus_split", "capex", "press_release", "postal_ballot",
    "agm_egm", "pledging", "unclassified",
]

# Subjects that tell us nothing on their own; the body decides, else the LLM.
GENERIC_SUBJECT = re.compile(
    r"^(general updates?|updates?|press release|media release|others?|"
    r"clarification.*|disclosure under regulation 30.*|company update|announcement)$", re.I)


@dataclass(frozen=True)
class Classification:
    category: str
    sub_type: str
    rule: str           # rule id, for traceability ("why is this here?")
    confident: bool     # False → send to the LLM if one is configured


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


# Routine compliance paperwork. Checked first so that, e.g., a trading-window
# closure that mentions "financial results" isn't mistaken for results.
ROUTINE = [
    ("trading_window", _rx(r"trading window")),
    ("share_certificate", _rx(r"(loss|duplicate|issue) of (share )?certificate|74\s*\(5\)|regulation 74")),
    ("investor_complaints", _rx(r"investor (complaints|grievance)")),
    ("compliance_cert", _rx(r"compliance certificate|certificate under (sebi|regulation)|"
                            r"secretarial compliance|regulation 40\(9\)|regulation 7\(3\)")),
    ("esop", _rx(r"\b(esop|esos|esps|rsu)s?\b|employee stock option|employees? stock")),
    ("esg", _rx(r"business responsibility|sustainability report|\bbrsr\b|\besg\b")),
    ("iepf", _rx(r"\biepf\b|unclaimed (dividend|shares)")),
    ("auditor", _rx(r"(appointment|re-?appointment|change) (of|in) (the )?(statutory |secretarial |internal |cost )?auditors?")),
    ("deviation", _rx(r"statement of deviation|monitoring agency")),
    ("large_corporate", _rx(r"large corporate")),
    ("record_book", _rx(r"closure of (register|book)")),
]

# Ordered: first match wins. Each entry: (rule id, category, pattern, sub_type fn)
def _results_sub(t: str) -> str:
    if re.search(r"newspaper|publication", t):
        return "newspaper_ad"
    if re.search(r"board meeting (to be held|intimation|scheduled)|intimation of board meeting|"
                 r"to consider and approve|will be held|proposes? to consider", t):
        return "intimation"
    if re.search(r"investor presentation|earnings presentation|results presentation", t):
        return "presentation"
    if re.search(r"press release|media release", t):
        return "press_release"
    return "outcome"


ROLE_KMP = r"(chief executive|\bceo\b|chief financial|\bcfo\b|managing director|\bmd\b|" \
           r"whole[- ]time director|executive director|chairman|chairperson|chief operating|\bcoo\b)"


def _mgmt_sub(t: str) -> str:
    leaving = bool(re.search(r"resign|cessation|ceas|retire|step(s|ped)? down|demise", t))
    if re.search(ROLE_KMP, t):
        role = "kmp"
    elif re.search(r"independent director|non[- ]executive|additional director|nominee director|director", t):
        role = "director"
    else:
        role = "other"   # company secretary, senior management, compliance officer
    return f"{role}_{'exit' if leaving else 'join'}"


def _rating_sub(t: str) -> str:
    if re.search(r"downgrad|negative|watch with negative", t):
        return "downgrade"
    if re.search(r"upgrad|positive", t):
        return "upgrade"
    if re.search(r"reaffirm|re-?affirm", t):
        return "reaffirm"
    return "other"


def _call_sub(t: str) -> str:
    if "transcript" in t:
        return "transcript"
    if re.search(r"audio|recording|video", t):
        return "recording"
    if re.search(r"earnings call|conference call|con\.? ?call|concall", t):
        return "notice"
    return "other"


def _fund_sub(t: str) -> str:
    if re.search(r"buy-?back", t):
        return "buyback"
    if re.search(r"commercial paper|debenture|\bncds?\b|bonds?\b", t):
        return "debt"
    return "equity"


def _pr_sub(t: str) -> str:
    if re.search(r"\border(s)?\b|contract|letter of (award|intent)|\bloa\b|bagging|award(ed)?\b", t):
        return "order_win"
    return "general"


RULES: list[tuple[str, str, re.Pattern, object]] = [
    ("results", "results", _rx(r"financial results?|\bresults? (for|of) the (quarter|half|year)|"
                               r"integrated filing.{0,5}financ|unaudited|audited (standalone|consolidated)"), _results_sub),
    ("call_transcript", "earnings_call", _rx(r"transcript|earnings call|conference call|con\.? ?call|concall|"
                                             r"audio recording|investors? call"), _call_sub),
    ("mgmt", "management_change", _rx(r"change in (directorate|management|key managerial|kmp|senior management)|"
                                      r"appointment|resignation|re-?designation|cessation|retirement|"
                                      r"step(s|ped)? down"), _mgmt_sub),
    ("pledge", "pledging", _rx(r"pledg|encumbrance|regulation 31\b"),
     lambda t: "release" if re.search(r"release|revoc", t) else "create"),
    ("insider", "insider_trading", _rx(r"insider trading|\bsast\b|regulation 7\s*\(2\)|reg(ulation)?\.? 29|"
                                       r"takeover regulations"), lambda t: "disclosure"),
    ("mna", "M&A", _rx(r"acquisition|acquire|amalgamation|merger|demerger|scheme of arrangement|"
                       r"joint venture|\bjv\b|divest|disinvest|sale of (stake|shares|undertaking|business)|"
                       r"slump sale|incorporation of .{0,30}subsidiary|investment in .{0,30}subsidiary|"
                       r"strategic investment"),
     lambda t: "subsidiary" if re.search(r"incorporation of|investment in .{0,30}subsidiary", t) else "deal"),
    ("fund", "fund_raise", _rx(r"qualified institutions? placement|\bqip\b|rights issue|preferential (issue|allotment)|"
                               r"buy-?back|commercial paper|non-convertible debenture|\bncds?\b|fund ?rais|"
                               r"raising of funds|issue of (equity|securities|debentures|bonds|warrants)|"
                               r"allotment of (equity|securities|debentures|warrants)"), _fund_sub),
    ("litigation", "litigation", _rx(r"litigation|dispute|regulatory action|show cause|penalt|\bfine[ds]?\b|"
                                     r"tax demand|demand order|\bgst\b.{0,40}(order|demand)|insolvency|\bnclt\b|"
                                     r"\bcourt\b|tribunal|arbitra|search and seizure|income tax (search|survey)|"
                                     r"warning letter|form 483|import alert|\busfda\b.{0,40}(observation|inspection)"),
     lambda t: "regulatory" if re.search(r"usfda|warning letter|483|sebi|rbi", t) else "legal"),
    ("rating", "credit_rating", _rx(r"credit rating|\brating\b.{0,60}(crisil|icra|care|india ratings|fitch|moody|s&p|acuite)|"
                                    r"(crisil|icra|care ratings|india ratings|acuite)"), _rating_sub),
    ("bonus_split", "bonus_split", _rx(r"\bbonus\b|sub-?division|stock split|split of (equity )?shares"),
     lambda t: "bonus" if "bonus" in t else "split"),
    ("dividend", "dividend", _rx(r"dividend"), lambda t: "declared"),
    ("capex", "capex", _rx(r"capex|capital expenditure|capacity expansion|expansion of capacity|"
                           r"new (plant|facility|manufacturing)|commissioning|commercial production|"
                           r"greenfield|brownfield"), lambda t: "capacity"),
    ("postal", "postal_ballot", _rx(r"postal ballot"), lambda t: "ballot"),
    ("agm", "agm_egm", _rx(r"\bagm\b|\begm\b|annual general meeting|extra-?ordinary general meeting|"
                           r"shareholders'? meeting|voting results|scrutini[sz]er|e-?voting"), lambda t: "meeting"),
    ("investor_meet", "investor_meetings", _rx(r"analysts?/institutional investor|investor meet|analyst meet|"
                                               r"investor conference|one[- ]on[- ]one|roadshow|"
                                               r"institutional investors?"), lambda t: "meeting"),
    ("investor_pres", "results", _rx(r"investor presentation"), lambda t: "presentation"),
    ("press", "press_release", _rx(r"press release|media release|launch|partnership|collaborat|\bmou\b|"
                                   r"memorandum of understanding|\border(s)?\b|contract|letter of (award|intent)|"
                                   r"bagging|clarification"), _pr_sub),
]


def classify(subject: str, body: str) -> Classification:
    subj = (subject or "").strip()
    text = f"{subj} || {body or ''}".lower()

    # Newspaper ads: results ads belong to 'results' (per the reference doc) but
    # carry almost no information; everything else is routine.
    if re.search(r"newspaper|publication of (financial )?results|copy of (the )?newspaper", text):
        if re.search(r"result", text):
            return Classification("results", "newspaper_ad", "routine:newspaper_results", True)
        return Classification("unclassified", "newspaper", "routine:newspaper", True)

    for rule_id, rx in ROUTINE:
        if rx.search(text):
            return Classification("unclassified", rule_id, f"routine:{rule_id}", True)

    # NSE files both concall notices and investor meetings under one subject
    # ("Analysts/Institutional Investor Meet/Con. Call Updates"); the body decides.
    if re.search(r"analysts?/institutional investor meet", subj, re.I):
        b = (body or "").lower()
        if re.search(r"transcript|recording|earnings|conference call|con\.? ?call|concall|results", b):
            return Classification("earnings_call", _call_sub(b), "rule:nse_meet_call", True)
        return Classification("investor_meetings", "meeting", "rule:nse_meet", True)

    for rule_id, category, rx, sub_fn in RULES:
        if rx.search(text):
            sub = sub_fn(text)  # type: ignore[operator]
            # Generic subject + a weak catch-all match (press/general) → let the LLM look.
            weak = category == "press_release" and sub == "general" and bool(GENERIC_SUBJECT.match(subj))
            return Classification(category, sub, f"rule:{rule_id}", not weak)

    if GENERIC_SUBJECT.match(subj) or not subj:
        return Classification("press_release" if "press" in subj.lower() else "unclassified",
                              "general", "default", False)
    return Classification("unclassified", "other", "default", False)
