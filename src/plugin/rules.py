"""The cost model: what every model turn carries, under eager and under lazy loading.

Only input tokens are counted, and a turn is one model call. Every count is a given integer, so
there is no tokenizer and no rounding anywhere.

Eager. Each turn's context is the system prompt, every schema in the catalog, the user request
and the history. There is one turn per tool use and one final turn that writes the answer.

Lazy. Each turn's context is the system prompt, every index entry, the load_tool definition, the
schemas loaded so far, the user request and the history. One extra turn calls load_tool before a
tool's first use; the schema it loads counts from the next turn on, not from the load turn
itself, and stays for the rest of the run. A tool used again is never reloaded.

History. Each earlier use adds its call and result tokens. Each earlier load adds load_call and
load_result. A schema is never in the history: it is counted once, among the loaded schemas.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from contract import CatalogTool, Fixed, Use

TIERS = (5, 10, 20, 50)
NAME = set("abcdefghijklmnopqrstuvwxyz0123456789_")
FIXED_FIELDS = ("system_tokens", "request_tokens", "load_tool_tokens", "load_call_tokens", "load_result_tokens")


class RuleError(ValueError):
    """A catalog or scenario file that does not follow the format."""


@dataclass(frozen=True)
class Costs:
    eager_turns: list[int]
    lazy_turns: list[int]

    @property
    def eager_total(self) -> int:
        return sum(self.eager_turns)

    @property
    def lazy_total(self) -> int:
        return sum(self.lazy_turns)

    @property
    def lazy_cheaper(self) -> bool:
        """Strictly fewer tokens. A tie is not cheaper."""
        return self.lazy_total < self.eager_total


def whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def read_catalog_data(data) -> list[CatalogTool]:
    """The catalog a parsed file states, or raise ``RuleError``."""
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list) or not data["tools"]:
        raise RuleError("a catalog holds a tools list with at least one tool")
    names, made = set(), []
    for item in data["tools"]:
        if not isinstance(item, dict):
            raise RuleError("every tool is an object")
        name = item.get("name")
        if not isinstance(name, str) or not name or set(name) - NAME:
            raise RuleError(f"every tool's name is lower-case letters, digits and underscores, not {name!r}")
        if name in names:
            raise RuleError(f"tool {name!r} is listed twice")
        for field in ("schema_tokens", "entry_tokens"):
            if not whole(item.get(field)):
                raise RuleError(f"{name}: {field} is a whole number of 0 or more, not {item.get(field)!r}")
        if item.get("tier") not in TIERS:
            raise RuleError(f"{name}: tier is one of {list(TIERS)}, not {item.get('tier')!r}")
        names.add(name)
        made.append(
            CatalogTool(
                name=name,
                schema_tokens=item["schema_tokens"],
                entry_tokens=item["entry_tokens"],
                tier=item["tier"],
            )
        )
    for size in TIERS:
        held = sum(1 for tool in made if tool.tier <= size)
        if held != size:
            raise RuleError(f"the catalog at size {size} holds {held} tools, not {size}")
    return made


def read_scenario_data(data, catalog: list[CatalogTool]) -> tuple[Fixed, list[Use]]:
    """The fixed counts and the plan a parsed scenario file states, or raise ``RuleError``."""
    if not isinstance(data, dict) or not isinstance(data.get("fixed"), dict):
        raise RuleError("a scenario holds a fixed object")
    for field in FIXED_FIELDS:
        if not whole(data["fixed"].get(field)):
            raise RuleError(f"fixed.{field} is a whole number of 0 or more, not {data['fixed'].get(field)!r}")
    fixed = Fixed(**{field: data["fixed"][field] for field in FIXED_FIELDS})
    if not isinstance(data.get("plan"), list):
        raise RuleError("a scenario holds a plan list")
    smallest = {tool.name for tool in catalog if tool.tier <= TIERS[0]}
    plan = []
    for position, item in enumerate(data["plan"], 1):
        if not isinstance(item, dict):
            raise RuleError(f"use {position} is not an object")
        if item.get("tool") not in smallest:
            raise RuleError(
                f"use {position}: {item.get('tool')!r} is not in the {TIERS[0]}-tool catalog, so the plan would change with size"
            )
        for field in ("call_tokens", "result_tokens"):
            if not whole(item.get(field)):
                raise RuleError(f"use {position}: {field} is a whole number of 0 or more, not {item.get(field)!r}")
        plan.append(Use(tool=item["tool"], call_tokens=item["call_tokens"], result_tokens=item["result_tokens"]))
    return fixed, plan


def catalog_at(catalog: list[CatalogTool], size: int) -> list[CatalogTool]:
    """The catalog at ``size``: every tool of that tier or smaller, in the file's order."""
    return [tool for tool in catalog if tool.tier <= size]


def costs_at(catalog: list[CatalogTool], fixed: Fixed, plan: list[Use], size: int) -> Costs:
    """Every turn's input tokens under each strategy, for the catalog at ``size``."""
    held = catalog_at(catalog, size)
    schemas = {tool.name: tool.schema_tokens for tool in held}
    all_schemas = sum(schemas.values())
    all_entries = sum(tool.entry_tokens for tool in held)

    # Eager: one turn per use, then one more. The whole catalog is in every turn.
    eager, history = [], 0
    for use in plan:
        eager.append(fixed.system_tokens + all_schemas + fixed.request_tokens + history)
        history += use.call_tokens + use.result_tokens
    eager.append(fixed.system_tokens + all_schemas + fixed.request_tokens + history)

    # Lazy: a load turn before a tool's first use. Its schema counts from the next turn on.
    base = fixed.system_tokens + all_entries + fixed.load_tool_tokens + fixed.request_tokens
    lazy, history, loaded = [], 0, 0
    seen: set[str] = set()
    for use in plan:
        if use.tool not in seen:
            lazy.append(base + loaded + history)  # the load turn: the schema is not here yet
            history += fixed.load_call_tokens + fixed.load_result_tokens
            loaded += schemas[use.tool]  # from the next turn on it is in the context, and stays
            seen.add(use.tool)
        lazy.append(base + loaded + history)
        history += use.call_tokens + use.result_tokens
    lazy.append(base + loaded + history)
    return Costs(eager_turns=eager, lazy_turns=lazy)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sources_sha256(catalog_text: str, scenario_text: str) -> str:
    return sha256_text(f"{sha256_text(catalog_text)}:{sha256_text(scenario_text)}")


def inside(workspace: Path, name: str) -> Path:
    relative = Path(name)
    root = Path(workspace).resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root) or path == root:
        raise RuleError(f"{name!r} must name a file inside the workspace")
    return path


def read_text(workspace: Path, name: str) -> str:
    path = inside(workspace, name)
    if not path.is_file():
        raise RuleError(f"no file at {name}")
    return path.read_text(encoding="utf-8")


def load_sources(workspace: Path, catalog_name: str, scenario_name: str):
    """(the catalog, the fixed counts, the plan, the hash of both files)."""
    catalog_text = read_text(workspace, catalog_name)
    scenario_text = read_text(workspace, scenario_name)
    try:
        catalog = read_catalog_data(json.loads(catalog_text))
        fixed, plan = read_scenario_data(json.loads(scenario_text), catalog)
    except json.JSONDecodeError as error:
        raise RuleError(f"not JSON: {error}") from error
    return catalog, fixed, plan, sources_sha256(catalog_text, scenario_text)
