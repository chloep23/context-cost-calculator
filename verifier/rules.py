"""The cost model, worked out again from the files alone.

This is the verifier's own reading and its own arithmetic. It shares no code with the plugin, so
a tool and the check of that tool cannot be wrong in the same way. The model is the one the
README and the task's instructions state: only input tokens, a turn is one model call, a loaded
schema counts from the turn after the load, and a schema is never in the history.
"""

import hashlib
import json
from pathlib import Path

TIERS = (5, 10, 20, 50)
NAME = set("abcdefghijklmnopqrstuvwxyz0123456789_")
FIXED_FIELDS = ("system_tokens", "request_tokens", "load_tool_tokens", "load_call_tokens", "load_result_tokens")


def whole(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def parse_catalog(data):
    """(the tools as dicts, None) or (None, what is wrong with the catalog)."""
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list) or not data["tools"]:
        return None, "a catalog holds a tools list with at least one tool"
    names, made = set(), []
    for item in data["tools"]:
        if not isinstance(item, dict):
            return None, "every tool is an object"
        name = item.get("name")
        if not isinstance(name, str) or not name or set(name) - NAME:
            return None, f"every tool's name is lower-case letters, digits and underscores, not {name!r}"
        if name in names:
            return None, f"tool {name!r} is listed twice"
        for field in ("schema_tokens", "entry_tokens"):
            if not whole(item.get(field)):
                return None, f"{name}: {field} is a whole number of 0 or more, not {item.get(field)!r}"
        if item.get("tier") not in TIERS:
            return None, f"{name}: tier is one of {list(TIERS)}, not {item.get('tier')!r}"
        names.add(name)
        made.append(dict(item))
    for size in TIERS:
        held = sum(1 for tool in made if tool["tier"] <= size)
        if held != size:
            return None, f"the catalog at size {size} holds {held} tools, not {size}"
    return made, None


def parse_scenario(data, catalog):
    """((fixed, plan), None) or (None, what is wrong with the scenario)."""
    if not isinstance(data, dict) or not isinstance(data.get("fixed"), dict):
        return None, "a scenario holds a fixed object"
    for field in FIXED_FIELDS:
        if not whole(data["fixed"].get(field)):
            return None, f"fixed.{field} is a whole number of 0 or more, not {data['fixed'].get(field)!r}"
    if not isinstance(data.get("plan"), list):
        return None, "a scenario holds a plan list"
    smallest = {tool["name"] for tool in catalog if tool["tier"] <= TIERS[0]}
    plan = []
    for position, item in enumerate(data["plan"], 1):
        if not isinstance(item, dict):
            return None, f"use {position} is not an object"
        if item.get("tool") not in smallest:
            return None, f"use {position}: {item.get('tool')!r} is not in the {TIERS[0]}-tool catalog, so the plan would change with size"
        for field in ("call_tokens", "result_tokens"):
            if not whole(item.get(field)):
                return None, f"use {position}: {field} is a whole number of 0 or more, not {item.get(field)!r}"
        plan.append(dict(item))
    return ({field: data["fixed"][field] for field in FIXED_FIELDS}, plan), None


def costs_at(catalog, fixed, plan, size):
    """(the eager turns, the lazy turns) for the catalog at ``size``."""
    held = [tool for tool in catalog if tool["tier"] <= size]
    schemas = {tool["name"]: tool["schema_tokens"] for tool in held}
    all_schemas = sum(schemas.values())
    all_entries = sum(tool["entry_tokens"] for tool in held)

    eager, history = [], 0
    for use in plan:
        eager.append(fixed["system_tokens"] + all_schemas + fixed["request_tokens"] + history)
        history += use["call_tokens"] + use["result_tokens"]
    eager.append(fixed["system_tokens"] + all_schemas + fixed["request_tokens"] + history)

    base = fixed["system_tokens"] + all_entries + fixed["load_tool_tokens"] + fixed["request_tokens"]
    lazy, history, loaded, seen = [], 0, 0, set()
    for use in plan:
        if use["tool"] not in seen:
            lazy.append(base + loaded + history)
            history += fixed["load_call_tokens"] + fixed["load_result_tokens"]
            loaded += schemas[use["tool"]]
            seen.add(use["tool"])
        lazy.append(base + loaded + history)
        history += use["call_tokens"] + use["result_tokens"]
    lazy.append(base + loaded + history)
    return eager, lazy


def expected(catalog, fixed, plan):
    """What every size's result must be: turns, totals and whether lazy is strictly cheaper."""
    made = []
    for size in TIERS:
        eager, lazy = costs_at(catalog, fixed, plan, size)
        made.append(
            {
                "size": size,
                "eager_turns": eager,
                "lazy_turns": lazy,
                "eager_total": sum(eager),
                "lazy_total": sum(lazy),
                "lazy_cheaper": sum(lazy) < sum(eager),
            }
        )
    return made


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sources_sha256(catalog_text, scenario_text):
    return sha256_text(f"{sha256_text(catalog_text)}:{sha256_text(scenario_text)}")


def read_text(workspace, name):
    if not isinstance(name, str) or not name:
        return None, f"{name!r} is not a file name"
    relative = Path(name)
    root = Path(workspace).resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root) or path == root:
        return None, f"{name!r} must name a file inside the workspace"
    if not path.is_file():
        return None, f"no file at {name}"
    if path.stat().st_size > 4_000_000:
        return None, f"{name} is too large to read"
    return path.read_text(encoding="utf-8"), None


def load(workspace, catalog_name, scenario_name):
    """(catalog, fixed, plan, source hash, None) or (None, None, None, None, what is wrong)."""
    catalog_text, problem = read_text(workspace, catalog_name)
    if problem:
        return None, None, None, None, problem
    scenario_text, problem = read_text(workspace, scenario_name)
    if problem:
        return None, None, None, None, problem
    try:
        catalog_data, scenario_data = json.loads(catalog_text), json.loads(scenario_text)
    except (ValueError, RecursionError) as error:
        return None, None, None, None, f"a source file is not JSON: {error}"
    catalog, problem = parse_catalog(catalog_data)
    if problem:
        return None, None, None, None, f"{catalog_name}: {problem}"
    pair, problem = parse_scenario(scenario_data, catalog)
    if problem:
        return None, None, None, None, f"{scenario_name}: {problem}"
    fixed, plan = pair
    return catalog, fixed, plan, sources_sha256(catalog_text, scenario_text), None
