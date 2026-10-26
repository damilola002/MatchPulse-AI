"""Application-owned neutral phrase templates tied to approved claim facts."""

from __future__ import annotations

from typing import Any


def _clock(value: int) -> str:
    total_seconds = value // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def approved_phrases(claim: dict[str, Any]) -> dict[str, str]:
    role = "home" if claim["team_role"] == "home" else "away"
    period = "first half" if claim["period"] == "first_half" else "second half"
    facts = claim["observed_facts"]
    if claim["claim_kind"] == "score_change":
        before = facts["score_before"]
        after = facts["score_after"]
        before_score = f"{before['home']}–{before['away']}"
        after_score = f"{after['home']}–{after['away']}"
        return {
            "direct": f"The {role} side scored, changing the score from {before_score} to {after_score}.",
            "concise": f"Score change: {before_score} to {after_score} after a goal by the {role} side.",
        }

    window = claim["window"]
    start = _clock(window["start_match_elapsed_ms"])
    end = _clock(window["end_match_elapsed_ms"])
    if claim["claim_kind"] == "shot_activity":
        count = facts["qualifying_shot_count"]
        return {
            "direct": f"The {role} side recorded {count} shots in the {period}, from {start} to {end} match time.",
            "concise": f"The {role} side recorded {count} shots in the {period}, through {end} match time.",
        }
    count = facts["qualifying_pressure_event_count"]
    return {
        "direct": f"The {role} side logged {count} pressure events in the {period}, from {start} to {end} match time.",
        "concise": f"The {role} side logged {count} pressure events in the {period}, through {end} match time.",
    }
