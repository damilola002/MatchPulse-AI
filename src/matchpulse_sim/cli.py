"""Small offline CLI for synthetic generation and event-log replay."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .generator import generate_events
from .models import MatchConfig, Scenario, default_fixtures
from .replay import replay_events
from .serialization import canonical_json, read_event_input_file, read_json, read_jsonl, write_json, write_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="matchpulse-sim", description="Generate and replay synthetic football match events.")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="generate a deterministic synthetic match")
    generate.add_argument("--scenario", choices=[scenario.value for scenario in Scenario], default=Scenario.BALANCED.value)
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--match-id", default=None)
    generate.add_argument("--format", choices=("jsonl", "json"), default="jsonl")
    generate.add_argument("--output", default="-", help="output path, or - for stdout")
    replay = commands.add_parser("replay", help="validate and replay a JSON or JSONL event stream")
    replay.add_argument("input", help="input JSON array or JSONL file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            config = MatchConfig(
                seed=args.seed,
                match_id=args.match_id or f"synthetic-match-{args.seed}",
                teams=default_fixtures(),
                scenario=Scenario(args.scenario),
            )
            events = generate_events(config)
            output = write_jsonl(events) if args.format == "jsonl" else write_json(events)
            if args.output == "-":
                sys.stdout.write(output)
            else:
                Path(args.output).write_text(output, encoding="utf-8", newline="\n")
            return 0

        source = read_event_input_file(args.input)
        events = read_jsonl(source) if Path(args.input).suffix.lower() == ".jsonl" else read_json(source)
        state = replay_events(events)
        sys.stdout.write(canonical_json(state.to_dict()) + "\n")
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(2, f"matchpulse-sim: error: {exc}\n")
    return 2
