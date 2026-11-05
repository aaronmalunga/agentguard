"""The frozen attack catalogue must never change. A new version gets a new folder (v1, v2...)."""

import hashlib
import json
from pathlib import Path

V0 = Path(__file__).resolve().parents[2] / "eval" / "attacks" / "v0"

FROZEN = {  # recorded 5 Nov 2026, before any guard rule existed (docs/evaluation-plan.md section 4)
    "dev.jsonl": "162d2f3115007e2aeba2313d7c62400dcb84a1aa1e4b30c7169303aa03856499",
    "heldout.jsonl": "b1cecf690965281c03d0a1f8ebe600c88845ff0a88b41c1e0288b11b33761ee7",
}


V1 = V0.parent / "v1"
FROZEN_V1 = {  # supplement, frozen 5 Nov 2026, still before any guard rule (evaluation-plan.md s.8)
    "dev.jsonl": "b7e41184a9dc1b9ebcc64543fec7a04297bfe502a116b19df3f495ad6892f1a0",
    "heldout.jsonl": "3ebf170bf1539a76d1cc5de6b62c9278d971abe66c791fa4c2a2d362c08199a9",
}


def test_v1_files_match_frozen_hashes():
    for name, digest in FROZEN_V1.items():
        assert sha256(V1 / name) == digest, f"v1 {name} changed after freezing"


def test_v1_ids_do_not_clash_with_v0():
    ids = set()
    for folder in (V0, V1):
        for name in FROZEN:
            for line in (folder / name).read_text(encoding="utf-8").splitlines():
                case_id = json.loads(line)["id"]
                assert case_id not in ids
                ids.add(case_id)
    assert len(ids) == 380


def sha256(path: Path) -> str:
    # Hash the bytes with LF endings, so a Windows checkout with CRLF gives the same answer.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_files_match_frozen_hashes():
    for name, digest in FROZEN.items():
        assert sha256(V0 / name) == digest, f"{name} changed after freezing"


def test_manifest_agrees():
    manifest = json.loads((V0 / "MANIFEST.json").read_text(encoding="utf-8"))
    for name, digest in FROZEN.items():
        assert manifest["files"][name]["sha256"] == digest


def test_no_case_in_both_splits_and_ids_unique():
    ids = {}
    for name in FROZEN:
        for line in (V0 / name).read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            assert case["id"] not in ids
            ids[case["id"]] = name
            assert case["synthetic"] is True
            assert case["expected_decision"] in {"approve", "ask", "block"}
    assert len(ids) == 260


def test_templates_do_not_leak_across_splits():
    seen = {}
    for name in FROZEN:
        for line in (V0 / name).read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            key = (case["family"], case["template"])
            assert seen.setdefault(key, name) == name, f"template {key} is in both splits"
