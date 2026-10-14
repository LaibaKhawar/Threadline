from datetime import UTC, date, datetime

import pytest

from app.extraction.temporal import extract_temporal, first_deadline

TUE = datetime(2026, 9, 15, 10, tzinfo=UTC)  # Tuesday


@pytest.mark.parametrize(
    ("text", "expected_end"),
    [
        ("by Friday", date(2026, 9, 18)),
        ("tomorrow", date(2026, 9, 16)),
        ("next Monday", date(2026, 9, 21)),
        ("end of the week", date(2026, 9, 18)),
        ("by end of month", date(2026, 9, 30)),
        ("in two weeks", date(2026, 9, 29)),
        ("Oct 3rd", date(2026, 10, 3)),
        ("3 October 2026", date(2026, 10, 3)),
        ("2026-10-01", date(2026, 10, 1)),
        ("mid-October", date(2026, 10, 15)),
        ("next week", date(2026, 9, 27)),
        ("3 days ago", date(2026, 9, 12)),
    ],
)
def test_resolves_relative_and_absolute_expressions(text: str, expected_end: date) -> None:
    ms = extract_temporal(text, TUE)
    assert ms, text
    assert ms[0].range_end.date() == expected_end


def test_spans_point_into_source_text() -> None:
    text = "I'll send it by Friday, thanks."
    m = extract_temporal(text, TUE)[0]
    assert text[m.start : m.end].startswith("by Friday")
    assert m.relation == "by"


def test_may_as_modal_is_not_a_month() -> None:
    assert extract_temporal("We may finish soon.", TUE) == []
    assert extract_temporal("We'll launch in May.", TUE)[0].range_start.month == 5


def test_explicit_date_wins_over_adjacent_weekday() -> None:
    ms = extract_temporal("on Wednesday 12 November", TUE)
    assert [m.date for m in ms] == [date(2026, 11, 12)]


def test_month_preference_past_vs_future() -> None:
    oct14 = datetime(2026, 10, 14, tzinfo=UTC)
    assert extract_temporal("in March", oct14, prefer="past")[0].range_start.year == 2026
    assert extract_temporal("in March", oct14, prefer="future")[0].range_start.year == 2027


def test_first_deadline_ignores_past_dates() -> None:
    assert first_deadline("I sent it yesterday", TUE) is None
    d = first_deadline("Review by Oct 2", TUE)
    assert d and d.date == date(2026, 10, 2)
