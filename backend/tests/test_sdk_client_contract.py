"""Contract: every OrionClient call site must match the nkz_platform_sdk API.

The SOTA refactor (cf5b228) deleted the module's local Orion client — whose
API was `OrionClient(base_url, context_url)` with a per-call `tenant_id`
argument — and switched to the SDK client without adapting the call sites:
constructors without tenant_id (TypeError), `settings.context_broker_url`
landed in the tenant slot, and per-call tenant arguments overflowed
`create_entity`/`delete_entity` or silently bound to `get_entity(options)` /
`query_entities(q)`. None of it failed at import time, only at request time.

These tests statically pin the SDK contract for every call site in app/ so a
half-done client migration can never ship silently again.
"""

import ast
import inspect
import pathlib

from nkz_platform_sdk.orion import OrionClient as SDKOrionClient

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


def _sdk_method_max_positional(name: str) -> int:
    sig = inspect.signature(getattr(SDKOrionClient, name))
    return sum(
        1
        for p in sig.parameters.values()
        if p.name != "self" and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    )


def test_every_orionclient_construction_passes_tenant():
    problems = []
    for f in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "OrionClient"):
                continue
            first = node.args[0] if node.args else None
            first_is_tenant = (
                (isinstance(first, ast.Name) and first.id.endswith("tenant_id"))
                or (isinstance(first, ast.Attribute) and first.attr == "tenant_id")
            )
            has_kw = any(kw.arg == "tenant_id" for kw in node.keywords)
            if not (has_kw or first_is_tenant):
                problems.append(f"{f.name}:{node.lineno} OrionClient(...) without tenant_id")
    assert not problems, "\n".join(problems)


def test_no_method_call_exceeds_sdk_positional_args():
    limits = {m: _sdk_method_max_positional(m) for m in (
        "create_entity", "get_entity", "delete_entity",
        "update_entity_attrs", "query_entities",
    )}
    problems = []
    for f in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in limits:
                continue
            if len(node.args) > limits[node.func.attr]:
                problems.append(
                    f"{f.name}:{node.lineno} {node.func.attr}(): "
                    f"{len(node.args)} positional args, SDK max {limits[node.func.attr]}"
                )
    assert not problems, "\n".join(problems)
