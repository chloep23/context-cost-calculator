"""The committed data, held to what makes the four sizes comparable, and the cost model checked
against numbers worked out by hand."""

from __future__ import annotations

import itertools
import json

import pytest
from helpers import FIXTURES

import verifier.rules as checked

CATALOG = json.loads((FIXTURES / "catalog.json").read_text())["tools"]
TIERS = (5, 10, 20, 50)


@pytest.mark.parametrize("size", TIERS)
def test_the_catalog_at_each_size_holds_exactly_that_many_tools(size: int) -> None:
    assert len([tool for tool in CATALOG if tool["tier"] <= size]) == size


@pytest.mark.parametrize(("smaller", "larger"), list(itertools.pairwise(TIERS)))
def test_each_catalog_is_contained_in_the_next(smaller: int, larger: int) -> None:
    inner = [tool["name"] for tool in CATALOG if tool["tier"] <= smaller]
    outer = [tool["name"] for tool in CATALOG if tool["tier"] <= larger]
    assert outer[: len(inner)] == inner


def test_every_name_is_unique_and_every_count_is_a_whole_number() -> None:
    names = [tool["name"] for tool in CATALOG]
    assert len(set(names)) == len(names)
    assert all(checked.whole(tool["schema_tokens"]) and checked.whole(tool["entry_tokens"]) for tool in CATALOG)
    assert all("description" not in tool for tool in CATALOG), "the agent is handed only what the arithmetic needs"


def test_an_index_entry_is_always_smaller_than_the_schema_it_stands_for() -> None:
    """The premise of lazy loading: carrying the entry costs less than carrying the schema."""
    for tool in CATALOG:
        assert tool["entry_tokens"] < tool["schema_tokens"], tool["name"]


@pytest.mark.parametrize("name", ["scenario.json", "scenario_tie.json", "scenario_empty.json", "scenario_twice.json", "scenario_all5.json"])
def test_every_scenario_only_plans_tools_from_the_five_tool_catalog(name: str) -> None:
    plan = json.loads((FIXTURES / name).read_text())["plan"]
    smallest = {tool["name"] for tool in CATALOG if tool["tier"] <= 5}
    assert {use["tool"] for use in plan} <= smallest, "a plan outside the 5-tool catalog would change with size"


def test_the_worked_example_in_the_readme_is_right() -> None:
    """The README's example, recomputed. If the model ever changes, this fails before the README
    quietly becomes a lie."""
    catalog = [
        {"name": n, "schema_tokens": s, "entry_tokens": e, "tier": 5}
        for n, s, e in (("a", 200, 20), ("b", 300, 25), ("c", 250, 22), ("d", 400, 30), ("e", 150, 18))
    ]
    fixed = {
        "system_tokens": 100,
        "request_tokens": 50,
        "load_tool_tokens": 30,
        "load_call_tokens": 10,
        "load_result_tokens": 5,
    }
    plan = [
        {"tool": "a", "call_tokens": 15, "result_tokens": 40},
        {"tool": "b", "call_tokens": 20, "result_tokens": 60},
    ]
    eager, lazy = checked.costs_at(catalog, fixed, plan, 5)
    assert eager == [1450, 1505, 1585] and sum(eager) == 4540
    assert lazy == [295, 510, 565, 880, 960] and sum(lazy) == 3210
    assert sum(lazy) < sum(eager)
