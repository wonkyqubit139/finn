import pytest

from finn.pipeline.classify import classify
from finn.pipeline.priority import score, tier

W = ["results", "M&A", "management_change"]

CASES = [
    # (subject, body, category, sub_type)
    ("Outcome of Board Meeting", "approving the Unaudited Financial Results for the quarter ended September 30, 2026",
     "results", "outcome"),
    ("Board Meeting Intimation", "Board Meeting to be held on 14-Nov-2026 to consider and approve the Quarterly "
     "Unaudited Financial results", "results", "intimation"),
    ("Financial Result Updates", "has submitted to the Exchange the financial results for the period ended "
     "September 30, 2026", "results", "outcome"),
    ("Copy of Newspaper Publication", "Newspaper publication of Financial Results", "results", "newspaper_ad"),
    ("Copy of Newspaper Publication", "Newspaper publication of notice of postal ballot", "unclassified", "newspaper"),
    ("Closure of Trading Window", "closure of trading window till 48 hours after declaration of financial results",
     "unclassified", "trading_window"),
    ("Change in Directorate", "appointment of Mr X as Chief Financial Officer", "management_change", "kmp_join"),
    ("Change in Management", "resignation of Ms Y from the position of Managing Director & CEO",
     "management_change", "kmp_exit"),
    ("Change in Directorate", "appointment of Ms Z as an Additional (Independent) Director",
     "management_change", "director_join"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript of the earnings call for Q2",
     "earnings_call", "transcript"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of meet with institutional investors",
     "investor_meetings", "meeting"),
    ("Credit Rating", "ICRA has downgraded the rating to [ICRA]AA-", "credit_rating", "downgrade"),
    ("Acquisition", "acquisition of 100% equity of ABC Pvt Ltd", "M&A", "deal"),
    ("Updates", "Incorporation of a wholly owned subsidiary in Singapore", "M&A", "subsidiary"),
    ("Allotment of Securities", "allotment of equity shares under ESOP Scheme 2020", "unclassified", "esop"),
    ("Qualified Institutions Placement", "opening of QIP issue; floor price Rs 1,200", "fund_raise", "equity"),
    ("Press Release", "Company bags order worth Rs 2,500 crore from NHAI", "press_release", "order_win"),
    ("Disclosures under Reg. 29(1) of SEBI (SAST) Regulations, 2011", "acquisition of shares by promoter group",
     "insider_trading", "disclosure"),
    ("Updates", "Receipt of warning letter from USFDA for Halol facility", "litigation", "regulatory"),
    ("Corporate Action-Board approves Bonus", "bonus issue in the ratio 1:1", "bonus_split", "bonus"),
    ("Appointment of Statutory Auditor", "re-appointment of statutory auditors", "unclassified", "auditor"),
    ("Shareholders meeting", "Voting results of the 45th Annual General Meeting", "agm_egm", "meeting"),
]


@pytest.mark.parametrize("subject,body,cat,sub", CASES)
def test_rules(subject, body, cat, sub):
    c = classify(subject, body)
    assert (c.category, c.sub_type) == (cat, sub), c


def test_generic_subject_goes_to_llm():
    c = classify("General Updates", "has informed the Exchange regarding a press release")
    assert not c.confident


def test_priority_ordering():
    # A CFO exit must outrank a dividend, which outranks routine paperwork.
    assert score("management_change", "kmp_exit", W) > score("dividend", "declared", W) > score("unclassified", "esop", W)
    assert tier(score("results", "outcome", W)) == "high"
    assert tier(score("results", "newspaper_ad", W)) == "routine"   # watched boost doesn't lift paperwork
    assert tier(score("unclassified", "esop", W)) == "routine"
