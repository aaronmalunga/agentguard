import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agentguard.money import fmt, line_total_cents, to_cents


@pytest.mark.parametrize("value,cents", [("24.99", 2499), (18.6, 1860), (0.1, 10), ("10", 1000), (3, 300),
                                         ("0.005", 1), ("-1.50", -150)])
def test_to_cents(value, cents):
    assert to_cents(value) == cents


def test_float_sum_that_breaks_naive_code():
    # 0.1 + 0.2 = 0.30000000000000004 as a float; in cents it is exactly 30
    assert to_cents(0.1) + to_cents(0.2) == to_cents("0.3")


@pytest.mark.parametrize("bad", ["abc", "nan", "inf", ""])
def test_rejects_non_money(bad):
    with pytest.raises(ValueError):
        to_cents(bad)


def test_negative_quantity_rejected():
    with pytest.raises(ValueError):
        line_total_cents("1.00", -1)


def test_fmt():
    assert fmt(123456) == "$1,234.56" and fmt(5) == "$0.05" and fmt(-150) == "-$1.50"


@given(st.integers(min_value=0, max_value=10**9))
def test_cents_round_trip(cents):
    assert to_cents(f"{cents // 100}.{cents % 100:02d}") == cents


def test_every_at_limit_benign_case_fits_in_cents():
    """The catalogue's 'exactly at the limit' and 'prior spend with room' cases must not fail on rounding."""
    root = Path(__file__).resolve().parents[2] / "eval" / "attacks"
    checked = 0
    for version in ("v0", "v1"):
        for split in ("dev", "heldout"):
            for line in (root / version / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
                case = json.loads(line)
                if case["family"] != "benign":
                    continue
                m, r = case["mandate"], case["request"]
                total = sum(line_total_cents(i["unit_price"], i["quantity"]) for i in r["items"])
                assert total <= to_cents(m["budget_total"]) - to_cents(m["spent_so_far"]), case["id"]
                for i in r["items"]:
                    assert to_cents(i["unit_price"]) <= to_cents(m["max_item_price"]), case["id"]
                checked += 1
    assert checked == 105   # 50 benign in v0 + 55 in v1
