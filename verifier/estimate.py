"""estimate_tokens: held to the guess it claims to make, and nothing more."""

from .checks import result

CHARACTERS_A_TOKEN = 4


def verify_input(value):
    if not isinstance(value.text, str) or not value.text:
        return result(False, "text holds at least one character")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if output_value.text != input_value.text:
        return result(False, "the text is not the one given")
    wanted = len(input_value.text) // CHARACTERS_A_TOKEN
    if output_value.tokens != wanted:
        return result(False, f"tokens reads {output_value.tokens}, not {len(input_value.text)} characters over {CHARACTERS_A_TOKEN}")
    return result(True, "the guess is the length over four", tokens=wanted)
