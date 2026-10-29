"""cost_key: every turn and total, worked out again."""

from .checks import result, verify_sources_input
from .rules import expected, load
from .task import given_sizes

verify_input = verify_sources_input


def verify_output(input_value, output_value, workspace):
    catalog, fixed, plan, source, problem = load(workspace, input_value.catalog, input_value.scenario)
    if problem:
        return result(False, problem)
    if output_value.source_sha256 != source:
        return result(False, "source_sha256 is not the hash of the catalog and the scenario")
    wanted = expected(catalog, fixed, plan)
    given = given_sizes(output_value)
    if given != wanted:
        bad = next((w for w, g in zip(wanted, given, strict=False) if w != g), None)
        where = f" at size {bad['size']}" if bad else ""
        return result(False, f"the answer key's numbers are not the ones the cost model gives{where}")
    return result(True, "the answer key follows the cost model", sizes=len(wanted))
