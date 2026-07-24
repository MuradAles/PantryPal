"""db.encode / db.decode round trip and corrupt-input handling.

SQLite has no array type, so every list column crosses this boundary. If decode
raises instead of degrading, one bad row takes down the profile endpoint.
"""

import pytest

from app import db


@pytest.mark.parametrize(
    "values",
    [
        [],
        ["cast iron skillet"],
        ["wok", "hot plate", "one pan"],
        # Non-ASCII survives: the brief expects non-English input not to crash.
        ["gochujang", "crème fraîche", "山椒"],
        # Quotes and braces would break a naive comma-joined encoding.
        ['a "quoted" thing', "brace}{", "comma,separated"],
    ],
)
def test_encode_decode_round_trip(values):
    assert db.decode(db.encode(values)) == values


def test_encode_produces_json_text():
    # The column is TEXT holding JSON, not a Python repr. A repr would use single
    # quotes and decode would reject the row on the next read.
    assert db.encode(["wok"]) == '["wok"]'


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json at all",
        "{",
        '["unterminated',
        "{'python': 'repr'}",
    ],
)
def test_decode_bad_input_returns_empty_list(raw):
    assert db.decode(raw) == []


@pytest.mark.parametrize(
    "raw",
    [
        '{"cookware": []}',
        '"a bare string"',
        "42",
        "null",
        "true",
    ],
)
def test_decode_valid_json_that_is_not_a_list_returns_empty_list(raw):
    # json.loads succeeds here, so the isinstance check is the only thing standing
    # between a dict and code that expects to iterate a list of strings.
    assert db.decode(raw) == []


def test_decode_never_raises_on_corrupt_input():
    # Belt and braces: the callers treat decode as total.
    for raw in ["\x00\x01", "[1,2,", "﻿[]", "[" * 500]:
        assert isinstance(db.decode(raw), list)
