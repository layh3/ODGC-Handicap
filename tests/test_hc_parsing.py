"""Tests for hc_parsing — no network, no sheet access."""

import json
import sys
import textwrap

import pytest

sys.path.insert(0, ".")
from hc_parsing import (
    _extract_course_name,
    parse_udisc_league_schedule,
)


def _enqueue_page(flat: list) -> str:
    """Wrap a devalue flat array in a minimal UDisc-style HTML page."""
    inner = json.dumps(json.dumps(flat))
    return f'<html><script>streamController.enqueue({inner})</script></html>'


# ---------------------------------------------------------------------------
# parse_udisc_league_schedule
# ---------------------------------------------------------------------------

def _event_obj(flat: list, short_id: str, date: str, name: str) -> dict:
    """Append shortId, startDate, name strings to flat; return an event object."""
    i_sid  = len(flat); flat.append(short_id)
    i_date = len(flat); flat.append(date)
    i_name = len(flat); flat.append(name)
    k_sid  = len(flat); flat.append("shortId")
    k_date = len(flat); flat.append("startDate")
    k_name = len(flat); flat.append("name")
    return {f"_{k_sid}": i_sid, f"_{k_date}": i_date, f"_{k_name}": i_name}


def test_schedule_parses_events():
    flat = []
    ev1 = _event_obj(flat, "AbCdEf", "2026-06-10", "League - Event #6")
    ev2 = _event_obj(flat, "XyZ123", "2026-05-10", "League - Event #5")
    flat.extend([ev1, ev2])
    page = _enqueue_page(flat)

    events = parse_udisc_league_schedule(page)
    assert len(events) == 2
    assert events[0]["date"] == "2026-06-10"  # newest first
    assert events[0]["shortId"] == "AbCdEf"
    assert events[1]["shortId"] == "XyZ123"


def test_schedule_deduplicates():
    flat = []
    ev = _event_obj(flat, "SameId", "2026-06-01", "Duplicate")
    flat.extend([ev, ev])
    page = _enqueue_page(flat)

    events = parse_udisc_league_schedule(page)
    assert len(events) == 1


def test_schedule_url_uses_shortid():
    flat = []
    ev = _event_obj(flat, "Abc123", "2026-06-01", "X")
    flat.append(ev)
    page = _enqueue_page(flat)

    events = parse_udisc_league_schedule(page)
    assert events[0]["url"] == "https://udisc.com/events/Abc123/leaderboard?round=1"


def test_schedule_skips_bad_dates():
    flat = []
    # Valid event
    ev_good = _event_obj(flat, "GoodId", "2026-06-10", "Good")
    # Event with non-date startDate
    i_sid = len(flat); flat.append("BadId")
    i_bad = len(flat); flat.append("not-a-date")
    i_nm  = len(flat); flat.append("Bad")
    k_sid = len(flat); flat.append("shortId")
    k_sd  = len(flat); flat.append("startDate")
    k_nm  = len(flat); flat.append("name")
    ev_bad = {f"_{k_sid}": i_sid, f"_{k_sd}": i_bad, f"_{k_nm}": i_nm}
    flat.extend([ev_good, ev_bad])
    page = _enqueue_page(flat)

    events = parse_udisc_league_schedule(page)
    assert len(events) == 1
    assert events[0]["shortId"] == "GoodId"


def test_schedule_empty_page():
    events = parse_udisc_league_schedule("<html></html>")
    assert events == []


# ---------------------------------------------------------------------------
# _extract_course_name
# ---------------------------------------------------------------------------

def _course_page(course_name: str) -> str:
    """Minimal page with a course object (has courseId + name) in the payload."""
    flat: list = []
    i_cid_val = len(flat); flat.append("some-uuid-1234")
    i_nm_val  = len(flat); flat.append(course_name)
    k_cid = len(flat); flat.append("courseId")
    k_nm  = len(flat); flat.append("name")
    course_obj = {f"_{k_cid}": i_cid_val, f"_{k_nm}": i_nm_val}
    flat.append(course_obj)
    return _enqueue_page(flat)


def test_extract_course_name_found():
    page = _course_page("Ferguson Forest Disc Golf Course")
    assert _extract_course_name(page) == "Ferguson Forest Disc Golf Course"


def test_extract_course_name_missing():
    assert _extract_course_name("<html></html>") == ""


def test_extract_course_name_no_course_obj():
    flat = [{"_0": 1}, "just a string"]
    page = _enqueue_page(flat)
    assert _extract_course_name(page) == ""
