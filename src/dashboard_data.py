"""Freeze the case-level decision ledger from the measured benchmark outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARMS = {
    "rules": "rules-test",
    "ollama": "ollama-test",
    "jev": "jev-test",
    "gate": "jev_gate-test",
}
SPECIAL = {
    "case-025": "Poucos detalhes",
    "case-026": "Duas equipes",
    "case-027": "Instrução no texto",
    "case-029": "Poucos detalhes",
    "case-030": "Duas equipes",
    "case-031": "Instrução no texto",
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build() -> str:
    cases = [case for case in read_jsonl(ROOT / "data/cases.jsonl") if case["split"] == "test"]
    comparison = json.loads((ROOT / "results/jev-comparison.json").read_text(encoding="utf-8"))
    thresholds = json.loads((ROOT / "results/gate-thresholds.json").read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in cases}
    if len(cases) != 24 or len(by_id) != 24:
        raise ValueError("Expected 24 unique frozen test cases")

    for case in cases:
        if hashlib.sha256(case["message"].encode("utf-8")).hexdigest() != case["sha256"]:
            raise ValueError(f"Source message hash changed in {case['id']}")

    runs = {}
    for arm, filename in ARMS.items():
        rows = read_jsonl(ROOT / f"results/{filename}.jsonl")
        indexed = {row["id"]: row for row in rows}
        if len(rows) != 24 or len(indexed) != 24 or set(indexed) != set(by_id):
            raise ValueError(f"{arm}: test case IDs differ")
        for case_id, row in indexed.items():
            case = by_id[case_id]
            expected = {"route": case["route"], "review": case["review"]}
            if row["sha256"] != case["sha256"] or row["expected"] != expected:
                raise ValueError(f"{arm}: input or label changed in {case_id}")
            if "prediction" not in row:
                raise ValueError(f"{arm}: missing prediction in {case_id}")
        runs[arm] = indexed

    for arm, filename in ARMS.items():
        rows = runs[arm].values()
        route = sum(row["prediction"]["route"] == row["expected"]["route"] for row in rows)
        review = sum(row["prediction"]["review"] == row["expected"]["review"] for row in rows)
        joint = sum(
            row["prediction"]["route"] == row["expected"]["route"]
            and row["prediction"]["review"] == row["expected"]["review"]
            for row in rows
        )
        summary = comparison[filename]
        for label, count in (("route_accuracy", route), ("review_accuracy", review), ("joint_accuracy", joint)):
            if round(summary[label] * 24) != count:
                raise ValueError(f"{arm}: {label} differs from the published summary")

    threshold_hash = hashlib.sha256((ROOT / "results/gate-thresholds.json").read_bytes()).hexdigest()
    if any(row["gate_thresholds_sha256"] != threshold_hash for row in runs["gate"].values()):
        raise ValueError("Gate decisions do not match the frozen calibration file")
    gate_paths = [row["prediction"].get("path") for row in runs["gate"].values()]
    if gate_paths.count("jev") != 19 or gate_paths.count("jev_to_ollama") != 5:
        raise ValueError("Gate path counts changed")

    report = {
        "schema_version": 1,
        "comparison": comparison,
        "thresholds": thresholds,
        "cases": [
            {
                "id": case["id"],
                "language": case["language"],
                "scenario": case["scenario"],
                "category": SPECIAL.get(case["id"], "Rota direta"),
                "message": case["message"],
                "expected": {"route": case["route"], "review": case["review"]},
                "predictions": {
                    arm: {
                        key: value
                        for key, value in runs[arm][case["id"]]["prediction"].items()
                        if key in {
                            "route", "review", "route_probs", "review_probability",
                            "route_confidence", "path", "elapsed_ms"
                        }
                    }
                    for arm in ARMS
                },
            }
            for case in cases
        ],
    }
    return "window.jevReport = " + json.dumps(report, ensure_ascii=False, separators=(",", ":")) + ";\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check the checked-in browser data")
    args = parser.parse_args()
    output = ROOT / "docs/report-data.js"
    content = build()
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            raise SystemExit("docs/report-data.js is stale; run python src/dashboard_data.py")
        print("Decision ledger matches frozen benchmark artifacts")
    else:
        output.parent.mkdir(exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(f"Wrote {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
