"""Small offline CLI for synthetic generation and event-log replay."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

from .generator import generate_events
from .models import MatchConfig, Scenario, default_fixtures
from .replay import replay_events
from .serialization import canonical_json, read_event_input_file, read_json, read_jsonl, write_json, write_jsonl
from .playback import PlaybackError, play_events


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
    serve = commands.add_parser("serve", help="run the local Phase 2 API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8001)
    play = commands.add_parser("play", help="feed a complete synthetic event stream to the local API")
    source = play.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="complete JSON or JSONL event stream")
    source.add_argument("--seed", type=int, help="generate a deterministic stream from a seed")
    play.add_argument("--scenario", choices=[scenario.value for scenario in Scenario], default=Scenario.BALANCED.value)
    play.add_argument("--match-id", default=None)
    play.add_argument("--speed", type=float, default=1.0, help="simulation time per wall-clock time; must be positive")
    play.add_argument("--resume", action="store_true", help="resume after verifying server match/run/event identity")
    play.add_argument("--base-url", default="http://127.0.0.1:8001")
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

        if args.command == "serve":
            if args.host not in {"127.0.0.1", "localhost", "::1"}:
                parser.error("serve host must be loopback")
            if not 1 <= args.port <= 65535:
                parser.error("serve port must be between 1 and 65535")
            import uvicorn
            uvicorn.run("matchpulse_sim.api.app:app", host=args.host, port=args.port)
            return 0

        if args.command == "play":
            if not math.isfinite(args.speed) or args.speed <= 0:
                parser.error("playback speed must be positive")
            if args.input:
                source_text = read_event_input_file(args.input)
                events = read_jsonl(source_text) if Path(args.input).suffix.lower() == ".jsonl" else read_json(source_text)
            else:
                config = MatchConfig(seed=args.seed, match_id=args.match_id or f"synthetic-match-{args.seed}", teams=default_fixtures(), scenario=Scenario(args.scenario))
                events = generate_events(config)
            state = replay_events(events)
            result = play_events(events, base_url=args.base_url, speed=args.speed, resume=args.resume)
            sys.stdout.write(canonical_json({"local_expected_state": state.to_dict(), "server_state": result}) + "\n")
            return 0

        source = read_event_input_file(args.input)
        events = read_jsonl(source) if Path(args.input).suffix.lower() == ".jsonl" else read_json(source)
        state = replay_events(events)
        sys.stdout.write(canonical_json(state.to_dict()) + "\n")
        return 0
    except (OSError, ValueError, PlaybackError) as exc:
        parser.exit(2, f"matchpulse-sim: error: {exc}\n")
    except KeyboardInterrupt:
        sys.stderr.write("matchpulse-sim: playback cancelled\n" if args.command == "play" else "matchpulse-sim: interrupted\n")
        return 130
    return 2
