import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentguard.mandate import Address, Mandate

HOME = Address(name="Thandi Mokoena", line1="14 Jacaranda Ave", city="Pretoria", postal_code="0181", country="ZA")
START = datetime(2026, 11, 1, tzinfo=UTC)


def mandate(**over):
    base = {"mandate_id": "M2", "version": 1, "buyer_instruction": "One pair of wireless earbuds, under $80.",
            "currency": "USD", "budget_total_cents": 8000, "max_item_price_cents": 8000,
            "max_quantity_per_item": 1, "allowed_categories": ("electronics_audio",),
            "allowed_merchants": ("soundmart",), "ship_to": HOME, "valid_from": START,
            "expires_at": START + timedelta(days=29)}
    return Mandate(**{**base, **over})


def test_valid_mandate_and_window():
    m = mandate()
    assert m.is_valid_at(START + timedelta(days=1))
    assert not m.is_valid_at(START - timedelta(seconds=1))
    assert m.is_valid_at(m.expires_at)                      # limits are inclusive
    assert not m.is_valid_at(m.expires_at + timedelta(seconds=1))


@pytest.mark.parametrize("over", [
    {"currency": "EUR"},
    {"budget_total_cents": 0},
    {"max_item_price_cents": 9000},                          # above the total budget
    {"max_quantity_per_item": 0},
    {"allowed_categories": ()},
    {"allowed_merchants": ()},
    {"expires_at": START},                                   # not after valid_from
    {"valid_from": datetime(2026, 11, 1), "expires_at": datetime(2026, 11, 30)},   # no timezone
    {"surprise_field": 1},                                   # unknown fields refused
])
def test_bad_mandates_are_refused(over):
    with pytest.raises(ValidationError):
        mandate(**over)


def test_immutable():
    m = mandate()
    with pytest.raises(ValidationError):
        m.budget_total_cents = 1


def test_fingerprint_is_stable_and_sensitive():
    assert mandate().fingerprint() == mandate().fingerprint()
    assert len(mandate().fingerprint()) == 64                 # fits PayPal custom_id (max 127 chars)
    assert mandate().fingerprint() != mandate(budget_total_cents=8001).fingerprint()


def test_revise_makes_a_new_version_and_keeps_the_old():
    old = mandate()
    new = old.revise(budget_total_cents=10000, max_item_price_cents=10000)
    assert (old.version, new.version) == (1, 2)
    assert old.budget_total_cents == 8000 and new.budget_total_cents == 10000
    assert old.fingerprint() != new.fingerprint()
    with pytest.raises(ValueError):
        old.revise(version=5)


def test_revoke():
    r = mandate().revoke()
    assert r.status == "revoked" and r.version == 2 and not r.is_valid_at(START + timedelta(days=1))


def test_same_place_ignores_recipient_name():
    other = HOME.model_copy(update={"name": "T. Mokoena c/o Reception"})
    assert HOME.same_place(other)
    assert not HOME.same_place(HOME.model_copy(update={"city": "Durban"}))


def test_every_catalogue_mandate_parses_without_changing_meaning():
    root = Path(__file__).resolve().parents[2] / "eval" / "attacks"
    parsed = 0
    for version in ("v0", "v1"):
        for split in ("dev", "heldout"):
            for line in (root / version / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
                raw = json.loads(line)["mandate"]
                m = Mandate.from_catalogue(raw)
                assert m.budget_total_cents == round(raw["budget_total"] * 100)
                assert m.ship_to.model_dump() == raw["ship_to"]
                parsed += 1
    assert parsed == 380
