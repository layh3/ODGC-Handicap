"""Tests for hc_matching — pure functions, no I/O."""

import sys
import pytest

sys.path.insert(0, ".")
from hc_matching import guess_course_from_layout
from gsheets import find_duplicate_row_in_data


# ---------------------------------------------------------------------------
# guess_course_from_layout
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("layout,expected", [
    # Larrimac — course name must appear; "Blue Tees" / "Yellow Tees" alone can't identify
    ("Larrimac Blues",                                    "lmb"),
    ("Larrimac Yellows",                                  "lmy"),
    ("Larrimac Disc Golf Course - YELLOWS; 18 holes",     "lmy"),
    # Real LETS layout text includes the full event title (has "Larrimac" inside)
    ("LETS #6 | LETS Larrimac Evening Tags Series - LETS #6 | UDisc Events | Blue Tees",  "lmb"),
    ("LETS #6 | LETS Larrimac Evening Tags Series - LETS #6 | UDisc Events | Yellow Tees","lmy"),
    # Almonte
    ("Monday Night Tags @Almonte | UDisc Events",         "alm"),
    ("Almonte Blues",                                     "alb"),   # "blues" → alb
    # Ferguson / Kemptville
    ("Ferguson Forest Disc Golf Course | Blue",           "kvb"),
    ("Ferguson Forest Blues",                             "kvb"),
    ("Ferguson Forest Wonderbread",                       "kvb"),   # Wonderbread = blue layout
    ("KDGC Tags 2026 | UDisc Events | Blue | Ferguson Forest Disc Golf Course", "kvb"),
    # Sandy Row
    ("Sandy Row Blue",                                    "sr"),
    ("ORANGE Sandy Row",                                  "sro"),
    ("Sandy Row Disc Golf Course | Blue",                 "sr"),
    # Ettyville
    ("MVP White",                                         "epw"),
    ("MVP Blue",                                         "epb"),
    ("Axiom White",                                       "eiw"),
    # Unknown — no course context
    ("LETS #6 | UDisc Events | Blue Tees",                None),
    ("Some random park we've never seen",                 None),
])
def test_guess_course_from_layout(layout, expected):
    assert guess_course_from_layout(layout) == expected


# ---------------------------------------------------------------------------
# find_duplicate_row_in_data
# ---------------------------------------------------------------------------

def _sheet_row(year, event, course, scores: dict, n_cols=10):
    row = [None] * n_cols
    row[0] = year
    row[1] = event
    row[2] = course
    for col, score in scores.items():
        row[col - 1] = score
    return row


def _data_with_rows(rows):
    header = [["header"]] * 13
    return header + rows


def test_dedup_finds_exact_match():
    scores = {4: 55, 5: 62, 6: 48}
    data = _data_with_rows([_sheet_row(26, "LETS05_lmb", "lmb", scores)])
    result = find_duplicate_row_in_data(data, 26, scores)
    assert result is not None
    r_idx, n, total, ev, crs = result
    assert n == 3
    assert ev == "LETS05_lmb"


def test_dedup_different_event_name_same_scores():
    scores = {4: 55, 5: 62, 6: 48}
    data = _data_with_rows([_sheet_row(26, "MondayTags07", "alm", scores)])
    result = find_duplicate_row_in_data(data, 26, scores)
    assert result is not None
    assert result[3] == "MondayTags07"


def test_dedup_wrong_year_not_matched():
    scores = {4: 55, 5: 62, 6: 48}
    data = _data_with_rows([_sheet_row(25, "LETS05_lmb", "lmb", scores)])
    assert find_duplicate_row_in_data(data, 26, scores) is None


def test_dedup_below_min_matches_not_flagged():
    scores = {4: 55, 5: 62}  # only 2 matches, below min_matches=3
    data = _data_with_rows([_sheet_row(26, "LETS05_lmb", "lmb", scores)])
    assert find_duplicate_row_in_data(data, 26, scores) is None


def test_dedup_empty_candidate():
    data = _data_with_rows([_sheet_row(26, "X", "y", {4: 55})])
    assert find_duplicate_row_in_data(data, 26, {}) is None
