"""Each tool's and task's typed input and output (see nanoagent.plugin.v0001.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    READ_SCENARIO = "read_scenario"
    COST_KEY = "cost_key"
    ESTIMATE_TOKENS = "estimate_tokens"


class Task(Enum):
    COMPARE_LOADING = "compare-loading"


class Size(Enum):
    FIVE = 5
    TEN = 10
    TWENTY = 20
    FIFTY = 50


CATALOG = "The catalog file, relative to the workspace, e.g. catalog.json"
SCENARIO = "The scenario file, relative to the workspace, e.g. scenario.json"
TOOL_NAME = "A tool's name, exactly as the catalog writes it"
RUN = "The run that read this task's files, as read_scenario returns it: copy it unchanged"
SOURCE_HASH = "sha256 over the catalog and scenario files the costs were worked out from"
TIER = "The smallest catalog this tool belongs to: 5, 10, 20 or 50. The smaller catalogs are contained in the larger"


@dataclass
class CatalogTool(Output):
    name: Annotated[str, TOOL_NAME]
    schema_tokens: Annotated[int, "Tokens its full schema takes in the context under eager loading"]
    entry_tokens: Annotated[int, "Tokens its one-line index entry takes under lazy loading"]
    tier: Annotated[int, TIER]


@dataclass
class Fixed(Output):
    system_tokens: Annotated[int, "Tokens of the system prompt, in every turn's context"]
    request_tokens: Annotated[int, "Tokens of the user's request, in every turn's context"]
    load_tool_tokens: Annotated[int, "Tokens of the load_tool definition, in every lazy turn's context"]
    load_call_tokens: Annotated[int, "Tokens a load_tool call adds to the history"]
    load_result_tokens: Annotated[int, "Tokens a load_tool result adds to the history, beside the schema it loads"]


@dataclass
class Use(Output):
    tool: Annotated[str, TOOL_NAME]
    call_tokens: Annotated[int, "Tokens of the tool call itself"]
    result_tokens: Annotated[int, "Tokens of what the tool returned"]


@dataclass
class SizeResult(Output):
    size: Annotated[Size, "The catalog size these numbers are for"]
    eager_turns: Annotated[list[int], "Each eager turn's input tokens, in order; one turn per use and one more"]
    lazy_turns: Annotated[list[int], "Each lazy turn's input tokens, in order; a load turn before each tool's first use"]
    eager_total: Annotated[int, "The eager turns added up"]
    lazy_total: Annotated[int, "The lazy turns added up"]
    lazy_cheaper: Annotated[bool, "Whether lazy spends strictly fewer tokens than eager; a tie is not cheaper"]


@dataclass
class ScenarioInput(Output):
    catalog: Annotated[str, CATALOG]
    scenario: Annotated[str, SCENARIO]


@dataclass
class ScenarioOutput(Output):
    run: Annotated[str, RUN]
    catalog: Annotated[list[CatalogTool], "Every tool in the file, in its order, with the tier it belongs to"]
    fixed: Annotated[Fixed, "The token counts that do not depend on the catalog"]
    plan: Annotated[list[Use], "The tool uses, in the order they happen"]
    source_sha256: Annotated[str, SOURCE_HASH]


@dataclass
class CostsOutput(Output):
    task: Annotated[ScenarioInput, "The task input, exactly as given"]
    run: Annotated[str, RUN]
    sizes: Annotated[list[SizeResult], "One result per catalog size, smallest first"]


@dataclass
class KeyOutput(Output):
    source_sha256: Annotated[str, SOURCE_HASH]
    sizes: Annotated[list[SizeResult], "One result per catalog size, smallest first"]


@dataclass
class EstimateInput(Output):
    text: Annotated[str, "The text to guess a token count for"]


@dataclass
class EstimateOutput(Output):
    text: Annotated[str, "The text as given"]
    tokens: Annotated[int, "Its length in characters divided by four, rounded down: a guess, not a count"]


TOOLS = {
    Tool.READ_SCENARIO: (ScenarioInput, ScenarioOutput),
    Tool.COST_KEY: (ScenarioInput, KeyOutput),
    Tool.ESTIMATE_TOKENS: (EstimateInput, EstimateOutput),
}
TASKS = {Task.COMPARE_LOADING: (ScenarioInput, CostsOutput)}
