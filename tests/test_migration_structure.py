from __future__ import annotations

import ast
from pathlib import Path


def test_initial_migration_uses_explicit_alembic_operations_only():
    source = Path("migrations/versions/0001_phase2_match_state.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "Base.metadata.create_all" not in source
    assert "Base.metadata.drop_all" not in source
    assert "op.create_table" in source
    assert "op.create_index" in source
    assert "op.drop_table(\"match_events\")" in source
    assert "op.drop_table(\"matches\")" in source
    assert "op.drop_index(\"ix_match_events_match_sequence\"" in source
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"create_all", "drop_all"}
        for node in ast.walk(tree)
    )
