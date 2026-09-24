# Jev Decision Lab

A small benchmark for placing an atomic decision model in front of a generative support assistant. Jev answers two judgments in one API request: the destination team (`Choice`) and whether a person should review the case (`Noul`). A gate keeps confident paired decisions and sends uncertain cases to a local LLM. A keyword router and the local LLM provide measured baselines.

All 32 cases are hand-authored and fictional. Portuguese and English variants share a scenario family, and the family stays wholly in validation (8 cases) or test (24 cases). The corpus includes negation, multiple teams, missing details and instructions embedded inside a message. Its size makes it an engineering diagnostic, not an estimate of real-world accuracy.

## Measured comparison

One authenticated run of the pinned `jev-1.13.0` model completed all 8 validation and 24 test cases without an API error. The [four-arm report](results/jev-comparison.json) uses identical test case IDs, labels and input hashes across engines. Half the test cases are in Portuguese and half in English.

| Engine | Route | Human review | Both correct | Median latency | Jev input tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Keyword rules | 22/24 | 22/24 | 21/24 | 0.01 ms | 0 |
| Local `qwen3:1.7b` | 13/24 | 16/24 | 11/24 | 355 ms | 0 |
| Jev | **24/24** | 22/24 | **22/24** | 817 ms | 10,974 |
| Jev with LLM fallback | 22/24 | 21/24 | 21/24 | 850 ms | 10,974 |

The validation-only calibration accepted 7/8 cases with both labels correct. On test, the gate retained 19 Jev decisions and sent 5 to Qwen. Only 3/5 fallbacks had both labels correct. Qwen fixed one Jev review error but changed two correct Jev routes to incorrect ones. This particular gate was worse than using Jev directly; the report keeps that negative result. A safer next design would use the uncertain decision to request human review or to guide an LLM draft without letting a weaker model overwrite the route, but that change needs a fresh test set.

The two Jev review misses were manual-route cases that the model did not flag for human review. A deterministic rule requiring review on manual routes is a plausible policy guard, but it was identified after inspecting the test errors and is not included in the frozen comparison. The set is small and intentionally diagnostic: these numbers are neither a production accuracy estimate nor evidence of a general advantage over another model. The Brier scores in the gate report cover only its 19 Jev-only decisions, and the report gives that denominator explicitly.

At the [published rate](https://docs.typesafe.ai/models) of $0.042 per million input tokens when this run was recorded, Jev input for the 24-case test was estimated at $0.00046091. Output tokens were free under that rate; local Qwen compute is excluded. Latency includes the local machine and network conditions of this one run.

## Reproduce the local baselines

Python 3.11+ and Ollama are sufficient. Pull `qwen3:1.7b` before the generative baseline.

```bash
python src/cases.py
python -m unittest discover -s test -v
python src/run.py --engine rules --split test
python src/run.py --engine ollama --split test
python src/report.py results/rules-test.jsonl results/ollama-test.jsonl --out results/local-baselines.json
```

The compact cases sometimes contain explicit routing words, which favors the keyword baseline. Its near-zero processing time excludes process startup and should not be compared as a full service latency.

## Reproduce Jev and calibrate the gate

Set `TYPESAFE_API_KEY` in the local environment. The key is sent only to the official TypeSafe endpoint and is never written to a result file. The adapter pins `jev-1.13.0` and rejects another returned model version. It validates the `Choice` distribution, `Noul` probability, confidence and token usage against the [official API contract](https://docs.typesafe.ai/api).

```bash
python src/run.py --engine jev --split validation
python src/calibrate.py results/jev-validation.jsonl --out results/gate-thresholds.json
python src/run.py --engine jev --split test
python src/run.py --engine jev_gate --split test --gate-thresholds results/gate-thresholds.json
python src/report.py results/rules-test.jsonl results/ollama-test.jsonl results/jev-test.jsonl results/jev_gate-test.jsonl --out results/jev-comparison.json
```

The calibration searches route-probability and review-certainty thresholds on validation only. It chooses the highest coverage with at least two accepted cases and the requested joint accuracy (100% by default). If none qualifies, the gate sends every case to the LLM. The test labels never enter threshold selection. Eight validation cases cannot establish that a threshold is safe in production; this is a transparent benchmark protocol. `Choice` confidence is logged separately from the selected class probability, and neither is interpreted as empirical accuracy.

The gate report splits Jev-only decisions from Jev-to-LLM fallbacks. It includes completion and error rates, route and review accuracy both on completed calls and all cases, route macro F1, Brier scores where probabilities exist, per-language results, p50/p95 latency, token usage, and confusion counts. A failed API call remains a failed case. The calibration file hash is attached to every gate result. To estimate input-token cost, pass the current published Jev rate through `--jev-input-usd-per-million`; the rate is never hardcoded into the benchmark.

CI checks the contract tests and comparability of the recorded runs without an API key. The Jev and gate files contain predictions derived from authenticated API calls, while the rule and Qwen files contain local executions. The source messages, labels and code were created for this public project; no employer records, prompts or benchmark output are included. The API key was held only in the process environment during the measured run and is not stored in this repository.

References: [TypeSafe API](https://docs.typesafe.ai/api), [Jev models](https://docs.typesafe.ai/models), [Choice and Noul primitives](https://docs.typesafe.ai/primitives), [confidence interpretation](https://docs.typesafe.ai/confidence).
