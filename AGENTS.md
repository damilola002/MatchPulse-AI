# MatchPulse AI project rules

## Project boundary

MatchPulse AI is completely independent of AI Tactical Match-Breaker. Do not inspect, copy, import, link, or otherwise depend on that project, its history, or its assets. Keep all work in this repository.

## Phases and approvals

- Use the phased roadmap in `docs/roadmap.md`. Never implement a future phase without explicit approval.
- Start with a read-only review before implementation.
- Run the agreed tests and validation after implementation.
- Complete a final read-only review before requesting commit approval.
- Commit and push each require separate explicit approval. Never configure remotes or publish without authorization.
- Do not install dependencies, start services, or run migrations unless the approved phase requires it.

## Engineering requirements

- Never introduce real secrets into the repository, examples, fixtures, logs, or documentation.
- Clearly label synthetic data anywhere users could mistake it for real match data.
- Statistical insights must be deterministic and traceable to evidence.
- AI narratives must not invent or imply unsupported match facts; ground claims in supplied evidence and validate outputs.
- Document architectural decisions that affect contracts, security, or deployment.
- Preserve versioned, validated data contracts and explicit replay/idempotency behavior as those phases are approved.
- Report all modified files and validation results.
