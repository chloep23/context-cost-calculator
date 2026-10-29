"""read_scenario: the catalog, the fixed counts and the plan, all recomputed from the files."""

from .checks import result, verify_sources_input
from .rules import load

verify_input = verify_sources_input


def verify_output(input_value, output_value, workspace):
    catalog, fixed, plan, source, problem = load(workspace, input_value.catalog, input_value.scenario)
    if problem:
        return result(False, problem)
    if output_value.source_sha256 != source:
        return result(False, "source_sha256 is not the hash of the catalog and the scenario")
    given = [(t.name, t.schema_tokens, t.entry_tokens, t.tier) for t in output_value.catalog]
    if given != [(t["name"], t["schema_tokens"], t["entry_tokens"], t["tier"]) for t in catalog]:
        return result(False, "the catalog is not the file's, in its order")
    given_fixed = {
        "system_tokens": output_value.fixed.system_tokens,
        "request_tokens": output_value.fixed.request_tokens,
        "load_tool_tokens": output_value.fixed.load_tool_tokens,
        "load_call_tokens": output_value.fixed.load_call_tokens,
        "load_result_tokens": output_value.fixed.load_result_tokens,
    }
    if given_fixed != fixed:
        return result(False, "the fixed counts are not the file's")
    if [(u.tool, u.call_tokens, u.result_tokens) for u in output_value.plan] != [
        (u["tool"], u["call_tokens"], u["result_tokens"]) for u in plan
    ]:
        return result(False, "the plan is not the file's, in its order")
    return result(True, "the catalog, the fixed counts and the plan are the files'", tools=len(catalog), uses=len(plan))
