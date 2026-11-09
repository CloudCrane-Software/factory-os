#!/usr/bin/env python3
"""EXAM-E1 Feature A: wave manifest parser.

Reads a wave manifest JSON file (argv[1]) whose cards[] fields follow
波次清单/wave-NN.json: task_id / debt / state / channel / mem_budget(_g) /
allowed_paths. Emits one JSONL line per card on stdout, in manifest card
order, with fixed key order task_id,debt,state,channel,mem_budget,n_paths
and compact separators (",", ":"); n_paths = len(allowed_paths).

Illegal input (missing file / bad JSON / missing card field): one line
"E: <reason>" on stderr, exit 2.
"""
import json
import sys

# Fixed output key order (contract: 键序固定).
OUT_KEYS = ("task_id", "debt", "state", "channel", "mem_budget", "n_paths")

# Required per-card input fields. The memory budget is stored as
# "mem_budget_g" in real wave manifests; "mem_budget" is accepted as the
# spec-listed spelling. Missing both is an error.
REQUIRED_FIELDS = ("task_id", "debt", "state", "channel", "allowed_paths")
MEM_BUDGET_KEYS = ("mem_budget_g", "mem_budget")


class InputError(Exception):
    """Illegal input: message goes to stderr as "E: <reason>", exit 2."""


def parse_manifest(path):
    """Load and validate the manifest; return the list of output dicts."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as err:
        raise InputError(f"cannot read manifest: {err.strerror or err}: {path}")
    except UnicodeDecodeError:
        raise InputError(f"manifest is not valid UTF-8: {path}")

    try:
        data = json.loads(text)
    except ValueError as err:
        raise InputError(f"invalid JSON: {err}")

    if not isinstance(data, dict):
        raise InputError("manifest must be a JSON object")
    if "cards" not in data:
        raise InputError("manifest missing field: cards")
    cards = data["cards"]
    if not isinstance(cards, list):
        raise InputError("manifest field cards is not a list")

    rows = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise InputError(f"card {index} is not an object")
        for field in REQUIRED_FIELDS:
            if field not in card:
                raise InputError(f"card {index} missing field: {field}")
        mem_budget = None
        for key in MEM_BUDGET_KEYS:
            if key in card:
                mem_budget = card[key]
                break
        else:
            raise InputError(
                f"card {index} missing field: mem_budget_g"
            )
        allowed_paths = card["allowed_paths"]
        if not isinstance(allowed_paths, list):
            raise InputError(f"card {index} allowed_paths is not a list")
        rows.append(
            {
                "task_id": card["task_id"],
                "debt": card["debt"],
                "state": card["state"],
                "channel": card["channel"],
                "mem_budget": mem_budget,
                "n_paths": len(allowed_paths),
            }
        )
    return rows


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("E: usage: exam-parse-manifest.py <manifest.json>\n")
        return 2
    if argv[1] in ("-h", "--help"):
        sys.stdout.write(
            "usage: exam-parse-manifest.py <manifest.json>\n"
            "Parses a wave manifest and prints one compact JSONL line per card.\n"
        )
        return 0
    try:
        rows = parse_manifest(argv[1])
    except InputError as err:
        sys.stderr.write(f"E: {err}\n")
        return 2
    except Exception as err:  # any other malformed input: never a traceback
        sys.stderr.write(f"E: invalid manifest input: {err}\n")
        return 2
    out = sys.stdout
    for row in rows:  # dict literal keeps contract key order; card order kept
        out.write(json.dumps(row, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
