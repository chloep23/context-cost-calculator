"""The compare-loading verdict: a gold run holds every constraint, and each one fails on its own
case with its own message; plus the per-call checks.

The cases are the five a verifier has to decide -- correct, wrong, missing, malformed, and the
boundaries where the cost model parts company with a reasonable guess.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from helpers import Run, failed, stage
from slimconfig import build_output, plain_output

import verifier
from contract import EstimateInput, KeyOutput, ScenarioOutput
from plugin import estimate_tokens
from verifier.task import TEXT

CONSTRAINTS = len(TEXT)


# ----- Correct -----


def test_a_gold_run_holds_every_constraint(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.gold()
    found = run.verdict()
    assert found["valid"], found["message"]
    assert found["score"] == 1.0 and found["message"].startswith(f"All {CONSTRAINTS} checks hold")
    assert [entry["ok"] for entry in found["details"]["constraints"]] == [True] * CONSTRAINTS
    assert len(json.dumps(found)) < 8000, "the verdict lands in the chat's context: keep it small"


@pytest.mark.parametrize(
    "scenario", ["scenario.json", "scenario_tie.json", "scenario_empty.json", "scenario_twice.json", "scenario_all5.json"]
)
def test_every_committed_scenario_has_a_valid_gold_run(tmp_path: Path, scenario: str) -> None:
    run = Run(tmp_path, scenario=scenario)
    run.gold()
    assert run.verdict()["valid"]


def test_the_main_scenario_crosses_over_between_sizes(tmp_path: Path) -> None:
    """Rule 6 made visible: eager wins on a small catalog, lazy wins once it grows."""
    run = Run(tmp_path)
    assert [entry.lazy_cheaper for entry in run.key.sizes] == [False, True, True, True]
    assert run.key.sizes[0].eager_total < run.key.sizes[0].lazy_total
    assert run.key.sizes[-1].lazy_total < run.key.sizes[-1].eager_total


# ----- Wrong -----


def test_a_wrong_turn_that_still_totals_right_fails_turns_exact_only(tmp_path: Path) -> None:
    """The reason turns and totals are checked apart: moving tokens from one turn to another
    leaves the total untouched."""
    run = Run(tmp_path)
    run.read()
    sizes = run.answer()
    sizes[0]["eager_turns"] = [sizes[0]["eager_turns"][0] + 7, sizes[0]["eager_turns"][1] - 7, sizes[0]["eager_turns"][2]]
    assert sum(sizes[0]["eager_turns"]) == sizes[0]["eager_total"], "the total is unchanged"
    run.report(sizes)
    found = run.verdict()
    assert failed(found) == ["turns-exact"], failed(found)
    assert "ize 5: eager_turns reads" in found["message"]
    assert found["score"] == pytest.approx(3 / 4)


def test_a_wrong_total_fails_totals_exact(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.read()
    sizes = run.answer()
    sizes[1]["lazy_total"] += 100
    run.report(sizes)
    found = run.verdict()
    assert "totals-exact" in failed(found) and "ize 10: lazy_total reads" in found["message"]


def test_a_tie_called_cheaper_fails_cheaper_exact(tmp_path: Path) -> None:
    """Rule 6: a tie is not cheaper."""
    run = Run(tmp_path, scenario="scenario_tie.json")
    run.read()
    sizes = run.answer()
    tied = next(entry for entry in sizes if entry["eager_total"] == entry["lazy_total"])
    assert tied["lazy_cheaper"] is False
    tied["lazy_cheaper"] = True
    run.report(sizes)
    found = run.verdict()
    assert failed(found) == ["cheaper-exact"]
    assert "it says lazy is cheaper, but lazy spends" in found["message"]


def test_counting_a_schema_in_the_history_too_fails(tmp_path: Path) -> None:
    """The easiest way to get lazy wrong: adding the loaded schema to the history as well."""
    run = Run(tmp_path)
    run.read()
    sizes = run.answer()
    broken = copy.deepcopy(sizes)
    broken[0]["lazy_turns"] = [v + (240 if i >= 2 else 0) for i, v in enumerate(broken[0]["lazy_turns"])]
    broken[0]["lazy_total"] = sum(broken[0]["lazy_turns"])
    run.report(broken)
    found = run.verdict()
    assert "turns-exact" in failed(found) and "totals-exact" in failed(found)



def test_an_answer_key_that_breaks_the_cost_model_fails_answer_key_right(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    key = plain_output(run.key)
    key["sizes"][0]["lazy_total"] += 5
    found = run.verdict(report, reference=build_output(key, KeyOutput))
    assert failed(found)[0] == "answer-key-right" and found["score"] == 0.0


# ----- Missing -----


def test_no_answer_key_fails_first_and_scores_zero(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    found = run.verdict(report, reference=None)
    assert failed(found)[0] == "answer-key" and found["score"] == 0.0 and "cost_key never read" in found["message"]


def test_costs_without_reading_the_scenario_fail_read_scenario(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.gold()
    (tmp_path / "reports" / run.run / "scenario.json").unlink()
    found = run.verdict()
    assert failed(found)[0] == "read-scenario" and found["score"] == 0.0
    assert "was never called in run" in found["message"]
    assert found["details"]["right"] == 4, "the numbers are still judged, and still right"


def test_a_missing_size_fails_all_sizes(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.read()
    run.report(run.answer()[:-1])
    found = run.verdict()
    assert failed(found) == ["all-sizes"]
    assert "1 of the four sizes is not reported (50)" in found["message"]
    assert found["score"] == pytest.approx(3 / 4)



def test_a_missing_source_file_fails_sources(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    (tmp_path / "scenario.json").unlink()
    found = run.verdict(report)
    assert "sources" in failed(found) and "No file at scenario.json" in found["message"]


# ----- Malformed -----


def test_a_plan_naming_a_tool_outside_the_catalog_fails_sources(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    path = tmp_path / "scenario.json"
    data = json.loads(path.read_text())
    data["plan"][0]["tool"] = "deploy_service"  # real, but tier 20: the plan would change with size
    path.write_text(json.dumps(data))
    found = run.verdict(report)
    assert "sources" in failed(found)
    assert "'deploy_service' is not in the 5-tool catalog" in found["message"]


def test_a_size_reported_twice_fails_submitted_shape(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    twice = copy.deepcopy(report)
    twice["sizes"].append(copy.deepcopy(twice["sizes"][0]))
    found = run.verdict(twice)
    assert failed(found) == ["submitted-shape"] and "size 5 is reported twice" in found["message"]


def test_a_negative_count_fails_submitted_shape(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    broken = copy.deepcopy(report)
    broken["sizes"][0]["eager_turns"][0] = -1
    found = run.verdict(broken)
    assert failed(found) == ["submitted-shape"] and "holds a negative count" in found["message"]


def test_a_turn_list_of_the_wrong_length_fails_turns_exact(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.read()
    sizes = run.answer()
    sizes[0]["eager_turns"] = sizes[0]["eager_turns"][:-1]
    run.report(sizes)
    found = run.verdict()
    assert "turns-exact" in failed(found)


@pytest.mark.parametrize(("token", "words"), [("../..", "is not a run token"), ("", "is not a run token"), ("0" * 16, "has no run")])
def test_a_run_that_is_not_this_workspace_s_fails_this_run(tmp_path: Path, token: str, words: str) -> None:
    run = Run(tmp_path)
    report = run.gold()
    found = run.verdict({**report, "run": token})
    assert failed(found)[0] == "this-run" and words in found["message"] and found["score"] == 0.0


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"tools": []}, "at least one tool"),
        ({"tools": [{"name": "a", "schema_tokens": 1, "entry_tokens": 1, "tier": 5}]}, "holds 1 tools, not 5"),
    ],
)
def test_a_catalog_that_breaks_the_format_fails_sources(tmp_path: Path, change: dict, words: str) -> None:
    run = Run(tmp_path)
    report = run.gold()
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **change}))
    found = run.verdict(report)
    assert "sources" in failed(found) and words in found["message"]


def test_a_negative_fixed_count_fails_sources(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    path = tmp_path / "scenario.json"
    data = json.loads(path.read_text())
    data["fixed"]["system_tokens"] = -1
    path.write_text(json.dumps(data))
    found = run.verdict(report)
    assert "sources" in failed(found) and "system_tokens is a whole number of 0 or more" in found["message"]



# ----- Boundary -----


def test_a_plan_with_no_tool_uses_is_one_turn_each(tmp_path: Path) -> None:
    run = Run(tmp_path, scenario="scenario_empty.json")
    for entry in run.key.sizes:
        assert len(entry.eager_turns) == 1 and len(entry.lazy_turns) == 1
    assert all(entry.lazy_cheaper for entry in run.key.sizes), "with nothing loaded, entries beat schemas everywhere"
    run.gold()
    assert run.verdict()["valid"]


def test_a_tool_used_twice_is_loaded_once(tmp_path: Path) -> None:
    """Three uses over two distinct tools: 4 eager turns, and 3 + 2 + 1 = 6 lazy turns."""
    run = Run(tmp_path, scenario="scenario_twice.json")
    first = run.key.sizes[0]
    assert len(first.eager_turns) == 4 and len(first.lazy_turns) == 6
    run.gold()
    assert run.verdict()["valid"]


def test_a_plan_using_every_tool_in_the_small_catalog(tmp_path: Path) -> None:
    """Four uses over four distinct tools: the most load overhead a plan here can carry."""
    run = Run(tmp_path, scenario="scenario_all5.json")
    first = run.key.sizes[0]
    assert len(first.eager_turns) == 5 and len(first.lazy_turns) == 9
    run.gold()
    assert run.verdict()["valid"]


def test_an_exact_tie_is_not_cheaper(tmp_path: Path) -> None:
    run = Run(tmp_path, scenario="scenario_tie.json")
    tied = [entry for entry in run.key.sizes if entry.eager_total == entry.lazy_total]
    assert tied, "the tie scenario should tie somewhere"
    assert all(entry.lazy_cheaper is False for entry in tied)
    run.gold()
    assert run.verdict()["valid"]


def test_lazy_loses_at_one_size_and_wins_at_a_larger_one(tmp_path: Path) -> None:
    run = Run(tmp_path)
    flags = [entry.lazy_cheaper for entry in run.key.sizes]
    assert flags[0] is False and flags[-1] is True
    assert flags == sorted(flags), "once lazy wins it keeps winning as the catalog grows"


def test_the_load_turn_does_not_carry_the_schema_it_is_fetching(tmp_path: Path) -> None:
    """Rule 3's sharpest edge, read straight off the numbers: the first lazy turn carries no
    schema at all, and the second carries exactly the first tool's."""
    run = Run(tmp_path)
    data = run.read()
    first = run.key.sizes[0]
    entries = sum(tool.entry_tokens for tool in data.catalog if tool.tier <= 5)
    base = data.fixed.system_tokens + entries + data.fixed.load_tool_tokens + data.fixed.request_tokens
    assert first.lazy_turns[0] == base, "the load turn is the base and nothing else"
    schema = next(tool.schema_tokens for tool in data.catalog if tool.name == data.plan[0].tool)
    history = data.fixed.load_call_tokens + data.fixed.load_result_tokens
    assert first.lazy_turns[1] == base + schema + history


# ----- The per-call checks -----


def test_every_tool_has_both_checks_on_its_module(tmp_path: Path) -> None:
    from contract import Tool

    assert set(verifier.TOOLS) == set(Tool)
    for tool in Tool:
        module = verifier.TOOLS[tool]
        for name in ("verify_input", "verify_output"):
            assert callable(module.__dict__.get(name)), f"{tool.value}: {module.__name__} has no {name}"


def test_verify_input_answers_for_every_tool(tmp_path: Path) -> None:
    run = Run(tmp_path)
    from contract import Tool

    valid = {
        Tool.READ_SCENARIO: run.given,
        Tool.COST_KEY: run.given,
        Tool.ESTIMATE_TOKENS: build_output({"text": "hello there"}, EstimateInput),
    }
    for tool, value in valid.items():
        found = verifier.verify_input(tool.value, value)
        assert found["valid"] is True, (tool.value, found["message"])


def test_verify_output_recomputes_the_scenario(tmp_path: Path) -> None:
    run = Run(tmp_path)
    data = plain_output(run.read())
    assert verifier.verify_output("read_scenario", run.given, build_output(data, ScenarioOutput), str(tmp_path))["valid"]
    changed = copy.deepcopy(data)
    changed["fixed"]["system_tokens"] += 1
    found = verifier.verify_output("read_scenario", run.given, build_output(changed, ScenarioOutput), str(tmp_path))
    assert not found["valid"] and "fixed counts are not the file's" in found["message"]


def test_the_estimator_is_checked_against_its_own_guess_not_the_catalog(tmp_path: Path) -> None:
    """estimate_tokens is honest about dividing by four; its check holds it to that and no more."""
    stage(tmp_path, "catalog.json", "scenario.json")
    given = build_output({"text": "Run a read-only SQL query against the warehouse"}, EstimateInput)
    found = estimate_tokens(given, tmp_path)
    assert found.tokens == len(given.text) // 4
    assert verifier.verify_output("estimate_tokens", given, found, str(tmp_path))["valid"]


def test_the_estimator_disagrees_with_the_counts_the_task_uses(tmp_path: Path) -> None:
    """Why it is a distractor: a guess from length is nowhere near any count the catalog gives,
    so taking it in place of a given count is simply wrong."""
    run = Run(tmp_path)
    data = run.read()
    text = "Run a read-only SQL query against the warehouse and return rows"
    guess = estimate_tokens(build_output({"text": text}, EstimateInput), tmp_path).tokens
    assert guess not in {tool.schema_tokens for tool in data.catalog}
    assert guess not in {tool.entry_tokens for tool in data.catalog}


# ----- The verdict's own shape -----


def test_every_verdict_entry_has_the_same_keys_and_says_why(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    broken = copy.deepcopy(report)
    broken["sizes"][0]["lazy_cheaper"] = True
    for found in (run.verdict(report), run.verdict(broken), run.verdict({**report, "run": "0" * 16})):
        entries = found["details"]["constraints"]
        order = [entry["id"] for entry in entries]
        assert order == list(TEXT)
        for position, entry in enumerate(entries):
            assert set(entry) == {"id", "constraint", "ok", "expected", "actual", "message"}
            assert (entry["message"] == "") == (entry["ok"] is True)
            if entry["ok"] is None:
                blocking = entry["message"].removeprefix("Not checked: ").removesuffix(" did not hold.").split(" and ")
                assert all(name in order[:position] for name in blocking), entry
        wrong = [entry for entry in entries if entry["ok"] is False]
        if wrong:
            more = f" (+{len(wrong) - 1} more)" if len(wrong) > 1 else ""
            assert found["message"] == f"{wrong[0]['id']}: {wrong[0]['message'].removesuffix('.')}{more}"


def test_the_readme_lists_every_constraint_as_the_verifier_names_it() -> None:
    import re

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+) \| `([a-z-]+)` \| ([^|]+) \|", readme, re.MULTILINE)
    assert [(int(n), name, text.strip()) for n, name, text in rows] == [(n, *e) for n, e in enumerate(TEXT.items(), 1)]
