# Context Cost Calculator

A `nanoagent.plugin/v0001` plugin that works out what a run costs in input tokens under two ways
of giving a model its tools — loading every schema up front, or loading each one on demand — and
says at which catalog sizes the lazy way is cheaper. Every count is a given whole number: no
tokenizer, no rounding. No network.

The catalog tools are **invented mock tools**, not this plugin's real tools.

## Tools

| Name | Kind | Does | Code |
|---|---|---|---|
| `read_scenario` | tool | Reads both files in one call: the catalog with tiers and token counts, the fixed counts, and the plan | `src/plugin/selecting.py` |
| `cost_key` | tool | Works out every turn and total under both strategies, at all four sizes | `src/plugin/selecting.py` |
| `estimate_tokens` | tool | Guesses a token count from text length, characters over four | `src/plugin/selecting.py` |
| `compare-loading` | task | Reports both strategies' turns, totals and the cheaper one at each size: runner `agent`, reference `cost_key` | `verifier/task.py` |

No tool computes a total for the agent. `read_scenario` hands over raw counts; slicing the
catalog by size, walking the turns and adding up is the task.

`estimate_tokens` is honest — it really does divide by four — and wrong here, because the counts
this task needs are given in the files and are not guesses.

## The rules

1. **A turn is one model call, and only input tokens are counted.** Each turn's input is
   everything in the context at that call.
2. **Eager.** Every turn's context is the system prompt, all the catalog's schemas, the user
   request and the history. One turn per tool use, plus one final turn that writes the answer —
   so `n + 1` turns for a plan of `n` uses.
3. **Lazy.** Every turn's context is the system prompt, all the catalog's index entries, the
   `load_tool` definition, the schemas loaded so far, the user request and the history. Before a
   tool's first use, one extra turn calls `load_tool` for it. **Its schema is not in the context
   on that load turn** — it arrives in the result, so it counts from the next turn on, and stays.
   A tool used again is never reloaded. So `n + d + 1` turns for `n` uses over `d` distinct tools.
4. **History.** Each earlier tool use adds its call tokens plus its result tokens. Each earlier
   `load_tool` call adds `load_call_tokens` plus `load_result_tokens`. **A schema is never in the
   history** — it is counted once, among the loaded schemas.
5. **Catalogs are nested** (5 ⊂ 10 ⊂ 20 ⊂ 50) and the plan only uses tools from the 5-tool
   catalog, so the plan is identical at every size and the four results are comparable.
6. **"Lazy is cheaper" means strictly fewer total input tokens.** A tie is not cheaper.

## A worked example

Small enough to check by hand. System 100, request 50, `load_tool` 30, `load_call` 10,
`load_result` 5. A 5-tool catalog:

```
A schema 200 entry 20    B schema 300 entry 25    C schema 250 entry 22
D schema 400 entry 30    E schema 150 entry 18          Σschema 1300   Σentry 115
plan: use A (call 15, result 40), then use B (call 20, result 60)
```

**Eager** — 2 uses, so 3 turns. Every turn carries `100 + 1300 + 50 = 1450` plus history:

| Turn | History | Input |
|---|---|---|
| 1 use A | 0 | **1450** |
| 2 use B | 15+40 = 55 | **1505** |
| 3 answer | 55 + 20+60 = 135 | **1585** |

Total **4540**.

**Lazy** — 2 uses over 2 distinct tools, so 5 turns. Every turn carries
`100 + 115 + 30 + 50 = 295` plus the schemas loaded so far, plus history:

| Turn | Loaded | History | Input |
|---|---|---|---|
| 1 load A | 0 | 0 | **295** |
| 2 use A | 200 | 15 | **510** |
| 3 load B | 200 | 15 + 55 = 70 | **565** |
| 4 use B | 500 | 70 + 15 = 85 | **880** |
| 5 answer | 500 | 85 + 80 = 165 | **960** |

Total **3210**, so lazy is cheaper here.

Note turn 1 carries no schema at all — A's schema is being fetched, not yet in the context — and
that the loads add only `10 + 5` to the history each, never the schema.

## The verdict

`verify_task` decides a `compare-loading` submission on 11 constraints, in order. A failure among
the first 7 scores 0; past them the score is **the share of the four sizes whose every number is
right**.

| # | Constraint | Holds when |
|---|---|---|
| 1 | `answer-key` | The answer key is for this task's files |
| 2 | `sources` | The catalog and the scenario are well formed |
| 3 | `answer-key-right` | The answer key follows the cost model |
| 4 | `this-run` | The report names a run of this workspace |
| 5 | `read-scenario` | read_scenario read this task's files in this run |
| 6 | `submitted-task` | The submitted report is for this task |
| 7 | `submitted-shape` | The submitted report is well formed |
| 8 | `all-sizes` | All four catalog sizes are reported exactly once, smallest first |
| 9 | `turns-exact` | Each size's per-turn input tokens are right, in order |
| 10 | `totals-exact` | Each size's eager and lazy totals are right |
| 11 | `cheaper-exact` | Each size says whether lazy is strictly cheaper; a tie is not cheaper |

Turns and totals are checked apart on purpose: a wrong per-turn figure that still adds to the
right total fails `turns-exact` and passes `totals-exact`.

`sources` is where comparability is enforced rather than assumed — the tiers must nest to
exactly 5, 10, 20 and 50, every planned tool must be in the 5-tool catalog, and every count must
be a whole number of zero or more.

The verifier never runs a model. It reads both files and works the whole cost model out again in
`verifier/rules.py`, which shares no code with the plugin.

## Layout

```text
.
├── nanoagent.yaml   # manifest (a slimconfig ManifestConfig): id, runtime, permissions, tools, tasks
├── contract.py      # each tool's and task's typed input and output: slimconfig Output classes
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env             # environment variable NAMEs this plugin needs, never values
├── src/plugin/      # the MCP server: __main__.py, its IMPLEMENTATIONS, and the plugin's own modules
├── tests/           # the suite, with the invented catalog and scenarios under fixtures/
├── ui/              # how the page draws the outputs: renderers.js and renderers.css
├── product/         # the product page a catalog shows: product.yaml and icon.svg
└── verifier/        # deterministic verifier package
```

`contract.py` is the one place a value's shape is declared. A tool that fails raises; NanoAgent
sees an MCP error.

The committed scenarios each turn on one rule: the main one where lazy loses at size 5 and wins
from 10, one tuned to an exact tie, one with no tool uses at all, one that uses a tool twice, and
one that uses every tool in the 5-tool catalog. `tests/test_data.py` asserts the invariants
rather than trusting them.

## Develop and run

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Publishing checks every plugin rule: push the plugin to a public GitHub repository
and submit its URL on RUSH Lab.
