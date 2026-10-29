"""The tools: read_scenario, cost_key (the reference) and estimate_tokens (a guess, not a count)."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from contract import EstimateInput, EstimateOutput, KeyOutput, ScenarioInput, ScenarioOutput, Size, SizeResult
from plugin.rules import TIERS, RuleError, costs_at, load_sources

RUN = secrets.token_hex(8)
REPORTS = "reports"
MARKER = "run.json"
RECEIPT = "scenario.json"
CHARACTERS_A_TOKEN = 4


def run_folder(workspace: Path, run: str = RUN) -> Path:
    folder = Path(workspace) / REPORTS / run
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / MARKER
    if not marker.is_file():
        marker.write_text(json.dumps({"run": run}), encoding="utf-8")
    return folder


def read_scenario(given: ScenarioInput, workspace: Path) -> ScenarioOutput:
    """The catalog, the fixed counts and the plan. It works out no cost of its own."""
    catalog, fixed, plan, source = load_sources(Path(workspace), given.catalog, given.scenario)
    receipt = {"run": RUN, "catalog": given.catalog, "scenario": given.scenario, "sha256": source}
    (run_folder(Path(workspace)) / RECEIPT).write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    return ScenarioOutput(run=RUN, catalog=catalog, fixed=fixed, plan=plan, source_sha256=source)


def cost_key(given: ScenarioInput, workspace: Path) -> KeyOutput:
    """Every turn and total under both strategies, at all four sizes. The task's reference."""
    catalog, fixed, plan, source = load_sources(Path(workspace), given.catalog, given.scenario)
    sizes = []
    for size in TIERS:
        costs = costs_at(catalog, fixed, plan, size)
        sizes.append(
            SizeResult(
                size=Size(size),
                eager_turns=costs.eager_turns,
                lazy_turns=costs.lazy_turns,
                eager_total=costs.eager_total,
                lazy_total=costs.lazy_total,
                lazy_cheaper=costs.lazy_cheaper,
            )
        )
    return KeyOutput(source_sha256=source, sizes=sizes)


def estimate_tokens(given: EstimateInput, workspace: Path) -> EstimateOutput:
    """A guess from length alone: characters divided by four.

    It knows nothing of the counts the catalog gives, which are the ones the task is worked out
    from, so taking its number in place of one of those is taking a guess over a given fact.
    """
    if not isinstance(given.text, str) or not given.text:
        raise RuleError("text holds at least one character")
    return EstimateOutput(text=given.text, tokens=len(given.text) // CHARACTERS_A_TOKEN)
