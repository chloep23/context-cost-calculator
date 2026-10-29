"""The compare-loading verdict: 13 constraints, in order, on the answer key, the run the
submission names, the receipt read_scenario left, the saved and submitted report, and the
numbers themselves.

A failure among the first 9 scores 0; otherwise the score is the share of the four catalog
sizes whose every number is right, so a report right about three sizes scores 0.75. Turns and
totals are checked apart, so a wrong turn that still adds up to the right total is caught.
"""

from pathlib import Path

from .checks import RECEIPT, constraint, read_json, result, run_folder, run_problem, summary
from .rules import TIERS, expected, load

TEXT = {
    "answer-key": "The answer key is for this task's files",
    "sources": "The catalog and the scenario are well formed",
    "answer-key-right": "The answer key follows the cost model",
    "this-run": "The report names a run of this workspace",
    "read-scenario": "read_scenario read this task's files in this run",
    "submitted-task": "The submitted report is for this task",
    "submitted-shape": "The submitted report is well formed",
    "all-sizes": "All four catalog sizes are reported exactly once, smallest first",
    "turns-exact": "Each size's per-turn input tokens are right, in order",
    "totals-exact": "Each size's eager and lazy totals are right",
    "cheaper-exact": "Each size says whether lazy is strictly cheaper; a tie is not cheaper",
}
ORDER = tuple(TEXT)
GATES = ORDER[:7]
ANSWER_CHECKS = ORDER[7:]
MOST_NAMED = 3
SUBMIT = "Work the costs out from what read_scenario gave you and submit them."


def named(names):
    shown = ", ".join(str(name) for name in names[:MOST_NAMED])
    return shown + (f" and {len(names) - MOST_NAMED} more" if len(names) > MOST_NAMED else "")


def also(words, names):
    return f" Also {words}: {named(names[1:])}." if len(names) > 1 else ""



def given_sizes(output):
    return [
        {
            "size": entry.size.value,
            "eager_turns": list(entry.eager_turns),
            "lazy_turns": list(entry.lazy_turns),
            "eager_total": entry.eager_total,
            "lazy_total": entry.lazy_total,
            "lazy_cheaper": entry.lazy_cheaper,
        }
        for entry in output.sizes
    ]


def shape_problem(sizes):
    listed = [entry["size"] for entry in sizes]
    repeated = [size for size in listed if listed.count(size) > 1]
    if repeated:
        return f"size {repeated[0]} is reported twice"
    for entry in sizes:
        for field in ("eager_turns", "lazy_turns"):
            if any(value < 0 for value in entry[field]):
                return f"size {entry['size']}: {field} holds a negative count"
        if entry["eager_total"] < 0 or entry["lazy_total"] < 0:
            return f"size {entry['size']}: a total is negative"
    return None


def verify_task(arguments, output, reference, workspace):
    """The verdict on a submitted compare-loading report (see the module's docstring)."""
    checks = {}

    def put(identifier, ok, expected_value=None, actual=None, message=""):
        checks[identifier] = constraint(identifier, TEXT[identifier], ok, expected_value, actual, message)

    def skip(identifier, *needs):
        blocking = [need for need in needs if checks[need]["ok"] is not True]
        checks[identifier] = constraint(identifier, TEXT[identifier], None, message=f"Not checked: {' and '.join(blocking)} did not hold.")

    def hold(*identifiers):
        return all(checks[identifier]["ok"] is True for identifier in identifiers)

    # 1-3: the sources and the answer key.
    catalog, fixed, plan, source, problem = load(workspace, arguments.catalog, arguments.scenario)
    if reference is None:
        put("answer-key", False, None, None, f"No answer key: cost_key never read {arguments.scenario}.")
    elif problem is None and reference.source_sha256 != source:
        put("answer-key", False, source[:16], reference.source_sha256[:16], "The answer key read other files than this task names.")
    else:
        put("answer-key", True)
    put("sources", problem is None, None, None, problem or "")
    wanted = []
    if hold("answer-key", "sources"):
        wanted = expected(catalog, fixed, plan)
        key = given_sizes(reference)
        put("answer-key-right", key == wanted, None, None, "The answer key's numbers are not the ones the cost model gives.")
    else:
        skip("answer-key-right", "answer-key", "sources")

    # 4-5: the run, and the receipt read_scenario left in it.
    run = output.run
    problem = run_problem(workspace, run)
    put("this-run", problem is None, None, run, problem or "")
    if hold("this-run", "sources"):
        where = f"{run_folder(run)}/{RECEIPT}"
        found, trouble = read_json(Path(workspace) / where)
        wanted_receipt = {"catalog": arguments.catalog, "scenario": arguments.scenario}
        if trouble == "missing":
            message = f"read_scenario was never called in run {run} (no {where}): read the files before working the costs out."
        elif trouble:
            message = f"{where} is not a receipt: {trouble}."
        elif not isinstance(found, dict) or found.get("run") != run:
            message = f"{where} was altered after read_scenario: it does not name run {run}."
        elif {key: found.get(key) for key in wanted_receipt} != wanted_receipt:
            message = f"read_scenario read {found.get('catalog')!r} and {found.get('scenario')!r}, not this task's."
        else:
            message = ""
        put("read-scenario", not message, None, None, message)
    else:
        skip("read-scenario", "this-run", "sources")

    # 6-7: the submitted report.
    given_task = {"catalog": output.task.catalog, "scenario": output.task.scenario}
    wanted_task = {"catalog": arguments.catalog, "scenario": arguments.scenario}
    put("submitted-task", given_task == wanted_task, wanted_task, given_task, f"The submitted report names {given_task}, not this task's. {SUBMIT}")
    sizes = given_sizes(output)
    if hold("submitted-task"):
        problem = shape_problem(sizes)
        put("submitted-shape", problem is None, None, None, f"The submitted report is malformed: {problem}" if problem else "")
    else:
        skip("submitted-shape", "submitted-task")
    # 8-11: the numbers.
    right = None
    if hold("answer-key-right", "submitted-shape"):
        by_size = {entry["size"]: entry for entry in sizes}
        listed = [entry["size"] for entry in sizes]
        missing = [size for size in TIERS if size not in by_size]
        if missing or listed != sorted(listed):
            message = (
                f"{len(missing)} of the four sizes {'is' if len(missing) == 1 else 'are'} not reported ({named(missing)})."
                if missing
                else "the sizes are not in order, smallest first"
            )
            put("all-sizes", False, list(TIERS), listed, message)
        else:
            put("all-sizes", True)
        for identifier, fields, describe in (
            ("turns-exact", ("eager_turns", "lazy_turns"), "turn"),
            ("totals-exact", ("eager_total", "lazy_total"), "total"),
            ("cheaper-exact", ("lazy_cheaper",), "verdict"),
        ):
            bad = []
            for want in wanted:
                got = by_size.get(want["size"])
                if got is not None and any(got[field] != want[field] for field in fields):
                    bad.append(want)
            if bad:
                first = bad[0]
                got = by_size[first["size"]]
                field = next(f for f in fields if got[f] != first[f])
                detail = (
                    f"{field} reads {got[field]}, but the cost model gives {first[field]}"
                    if field != "lazy_cheaper"
                    else f"it says lazy is {'cheaper' if got[field] else 'not cheaper'}, but lazy spends {first['lazy_total']} against eager's {first['eager_total']}"
                )
                put(
                    identifier,
                    False,
                    {first["size"]: first[field]},
                    {first["size"]: got[field]},
                    f"size {first['size']}: {detail}.{also('wrong', [entry['size'] for entry in bad])}",
                )
            else:
                put(identifier, True)
        right = sum(
            1
            for want in wanted
            if by_size.get(want["size"]) == want
        )
    else:
        for identifier in ANSWER_CHECKS:
            skip(identifier, "answer-key-right", "submitted-shape")

    constraints = [checks[identifier] for identifier in ORDER]
    valid = all(entry["ok"] is True for entry in constraints)
    if any(checks[identifier]["ok"] is not True for identifier in GATES) or right is None:
        score = 0.0
    else:
        score = right / len(TIERS)
    details = {"constraints": constraints, "sizes": len(TIERS)}
    if right is not None:
        details["right"] = right
    if valid:
        cheaper = [want["size"] for want in wanted if want["lazy_cheaper"]]
        where = f"lazy is cheaper at {cheaper}" if cheaper else "lazy is never cheaper"
        return result(True, f"All {len(constraints)} checks hold: {where}.", score=1.0, **details)
    return result(False, summary(constraints), score=min(score, 0.99), **details)
