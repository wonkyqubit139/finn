from datetime import date

from finn.analysis.periods import (fy_of, fy_quarters, label, parse_period, parse_quarter_ended,
                                   period_for_filing, shift_quarters)


def test_fy_basics():
    assert label(date(2026, 9, 30)) == "Q2 FY27"
    assert label(date(2027, 3, 31)) == "Q4 FY27"
    assert label(date(2026, 3, 31)) == "Q4 FY26"
    assert fy_of(date(2026, 6, 30)) == 27
    assert fy_quarters(27) == [date(2026, 6, 30), date(2026, 9, 30), date(2026, 12, 31), date(2027, 3, 31)]
    assert shift_quarters(date(2026, 9, 30), -4) == date(2025, 9, 30)
    assert shift_quarters(date(2026, 12, 31), 1) == date(2027, 3, 31)


def test_filing_period():
    assert parse_quarter_ended("results for the quarter ended September 30, 2026") == date(2026, 9, 30)
    assert parse_quarter_ended("Quarter ended 30.09.2026") == date(2026, 9, 30)
    assert parse_quarter_ended("quarter ended 30th June 2026") == date(2026, 6, 30)
    assert parse_quarter_ended("year ended 31-Mar-2026") == date(2026, 3, 31)
    assert parse_quarter_ended("nothing here") is None
    # no date in text: results filed 20 Oct → Q2; filed 3 Oct (within a week of quarter end) → still Q1
    assert period_for_filing(date(2026, 10, 20)) == date(2026, 9, 30)
    assert period_for_filing(date(2026, 10, 3)) == date(2026, 6, 30)


def test_guidance_periods():
    ref = date(2026, 6, 30)   # said on the Q1 FY27 call
    assert parse_period("Q3 FY27", ref)["quarters"] == [date(2026, 12, 31)]
    assert parse_period("H2 FY27", ref)["quarters"] == [date(2026, 12, 31), date(2027, 3, 31)]
    assert parse_period("FY2027", ref)["label"] == "FY27"
    assert parse_period("for FY'27", ref)["label"] == "FY27"
    assert parse_period("next quarter", ref)["label"] == "Q2 FY27"
    assert parse_period("second half of the year", ref)["label"] == "H2 FY27"
    assert parse_period("this financial year", ref)["label"] == "FY27"
    assert parse_period("next year", ref)["label"] == "FY28"
    assert parse_period("over the medium term", ref) is None
