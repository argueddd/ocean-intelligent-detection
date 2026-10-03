#!/usr/bin/env python3
"""Inspect a user-selected acoustic file; never infer missing waveform axes."""
import argparse
import json
from pathlib import Path
import sys
from acoustic_inspection.pipeline import execute, exit_code


def reject_constant(value):
    raise ValueError(f"Invalid JSON numeric constant: {value}")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(text):
    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("probe", "run", "execute"))
    parser.add_argument("file", type=Path)
    configuration = parser.add_mutually_exclusive_group()
    configuration.add_argument("--config", type=Path)
    configuration.add_argument("--config-json", help="Explicit run configuration JSON, for execute only.")
    parser.add_argument("--file", dest="selected_file", help="Relative file within an execute directory input.")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.action == "execute":
        from acoustic_inspection.execution import execute_request
        output, code = execute_request(args, parse_json)
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return code
    if args.out is None:
        parser.error("the following arguments are required: --out")
    if args.config_json is not None or args.selected_file is not None:
        parser.error("--config-json and --file are only available with execute.")
    if args.action == "probe" and args.config:
        parser.error("probe does not accept a run configuration.")
    try:
        config = {}
        if args.config:
            config = parse_json(args.config.read_text(encoding="utf-8"))
        result = execute(args.file, args.out, config,
                         config_source=str(args.config.resolve()) if args.config else "no supplied configuration",
                         probe_only=args.action == "probe")
        print(json.dumps(dict(status=result["status"], result=str(args.out.resolve()/"result.json"),
                              issues=result["issues"]), ensure_ascii=False, allow_nan=False))
        return exit_code(result)
    except (OSError, ValueError) as e:
        print(json.dumps(dict(status="failed", error=str(e)), ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
