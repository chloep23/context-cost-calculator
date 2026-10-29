"""Staging a workspace and running the prescribed path, as the host runs a compare-loading task."""

from __future__ import annotations

import shutil
from pathlib import Path

from slimconfig import build_output, plain_output

import verifier
from contract import CostsOutput, KeyOutput, ScenarioInput
from plugin import cost_key, read_scenario

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CATALOG = "catalog.json"
SCENARIO = "scenario.json"
TIERS = (5, 10, 20, 50)


def stage(workspace: Path, *names: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy(FIXTURES / name, workspace / name)


class Run:
    """One task's workspace: the staged files, the tools, and the verdict on what was submitted."""

    def __init__(self, workspace: Path, scenario: str = SCENARIO, catalog: str = CATALOG) -> None:
        self.workspace = workspace
        self.task = {"catalog": catalog, "scenario": scenario}
        stage(workspace, catalog, scenario)
        self.given = build_output(self.task, ScenarioInput)
        self.submitted: dict | None = None
        self.run = ""
        self.key: KeyOutput = build_output(plain_output(cost_key(self.given, workspace)), KeyOutput)

    def read(self):
        found = read_scenario(self.given, self.workspace)
        self.run = found.run
        return found

    def report(self, sizes: list[dict]) -> dict:
        """What the agent submits: the whole answer, built from what read_scenario gave it."""
        self.submitted = {"task": self.task, "run": self.run, "sizes": sizes}
        return self.submitted

    def answer(self) -> list[dict]:
        """The answer key, in the shape report_costs takes."""
        return [
            {
                "size": entry.size.value,
                "eager_turns": list(entry.eager_turns),
                "lazy_turns": list(entry.lazy_turns),
                "eager_total": entry.eager_total,
                "lazy_total": entry.lazy_total,
                "lazy_cheaper": entry.lazy_cheaper,
            }
            for entry in self.key.sizes
        ]

    def gold(self) -> dict:
        self.read()
        return self.report(self.answer())

    def verdict(self, report: dict | None = None, reference: KeyOutput | None = ...) -> dict:
        found = report if report is not None else self.submitted
        return verifier.verify_task(
            "compare-loading",
            self.given,
            build_output(found, CostsOutput),
            self.key if reference is ... else reference,
            str(self.workspace),
        )


def failed(verdict: dict) -> list[str]:
    return [entry["id"] for entry in verdict["details"]["constraints"] if entry["ok"] is False]


def unchecked(verdict: dict) -> list[str]:
    return [entry["id"] for entry in verdict["details"]["constraints"] if entry["ok"] is None]
