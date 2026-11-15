"""Real NSE filings (Nov 2026, from the live feed) that the first rule set got
wrong. Public exchange text, kept verbatim as regressions."""
import pytest

from finn.pipeline.classify import classify
from finn.text import headline

REAL = [
    ("Action(s) taken or orders passed", "Bharti Airtel Limited has informed the Exchange about Action(s) taken or orders passed",
     "litigation", "regulatory"),
    ("General Updates", "Maruti Suzuki India Limited has informed the Exchange about Reference to the Financial Results issued by Suzuki Motor Corporation",
     "press_release", "general"),
    ("General Updates", "Titan Company Limited has informed the Exchange about Redemption of Commercial Paper",
     "unclassified", "debt_servicing"),
    ("General Updates", "HDFC Bank Limited has informed the Exchange about Approval from the Reserve Bank of India for re-appointment of Mr. V. Srinivasa Rangan asthe Whole-time Director (designated as Executive Director) of HDFC Bank Limited",
     "management_change", "kmp_reappoint"),
    ("Change in Director(s)", "HDFC Bank Limited has informed the Exchange regarding Change in Director(s) of the company.",
     "management_change", "unspecified"),
    ("Change in Management", "Hindustan Aeronautics Limited has informed the Exchange about change in Management",
     "management_change", "unspecified"),
    ("Retirement", "Titan Company Limited has informed the Exchange about Retirement of Mr. Noel N. Tata as Director and Vice-Chairman",
     "management_change", "kmp_retire"),
    ("General Updates", "Polycab India Limited has informed the Exchange about Analyst(s)/Investor(s) meet.",
     "investor_meetings", "meeting"),
    ("General Updates", "Titan Company Limited has informed the Exchange about Certificate pursuant to SEBI Circular no. SEBI/HO/DDHS/P/CIR/2021/613 dated August 10, 2021",
     "unclassified", "compliance_cert"),
    ("General Updates", "Trent Limited has informed the Exchange about Reminder letter to shareholders to Dematerialise the Shares",
     "unclassified", "demat_reminder"),
    ("Updates", "Bharti Airtel Limited has informed the Exchange regarding 'Bharti Airtel Limited has informed the Exchange regarding Quarterly Report w.r.t. Financial Results second quarter (Q2) and six months ended September 30, 2026.'.",
     "results", "presentation"),
    # these were already right and must stay right
    ("Outcome of Board Meeting", "Titan Company Limited has submitted to the Exchange, the financial results for the period ended September 30, 2026.",
     "results", "outcome"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Titan Company Limited has informed the Exchange about Earnings Call Transcripts",
     "earnings_call", "transcript"),
    ("Copy of Newspaper Publication", "Newspaper publication for Unaudited financial results for the second quarter and halfyear ended 30th September 2026",
     "results", "newspaper_ad"),
    ("Credit Rating- Others", "Hindustan Aeronautics Limited has informed the Exchange about Credit Rating- withdrawal",
     "credit_rating", "other"),
]


@pytest.mark.parametrize("subject,body,cat,sub", REAL)
def test_real_filings(subject, body, cat, sub):
    c = classify(subject, body)
    assert (c.category, c.sub_type) == (cat, sub), (subject, body, c)


def test_real_headlines():
    assert headline("Outcome of Board Meeting", "Titan Company Limited has submitted to the Exchange, the financial "
                    "results for the period ended September 30, 2026.", None) == \
        "The financial results for the period ended September 30, 2026."
    assert headline("Updates", "Bharti Airtel Limited has informed the Exchange regarding 'Bharti Airtel Limited has "
                    "informed the Exchange regarding Quarterly Report w.r.t. Financial Results second quarter (Q2).'.",
                    None) == "Quarterly Report w.r.t. Financial Results second quarter (Q2)."
