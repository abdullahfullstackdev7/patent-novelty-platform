"""JSON schema helpers: provider-safe schemas, sub-schema lookup and cache keys."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel

from app.llm.types import Message

# Keywords that strict structured-output modes reject. Pydantic validates them locally anyway.
_UNSUPPORTED = {
    "minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum", "pattern",
    "format", "default", "title", "examples", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "uniqueItems", "minProperties", "maxProperties",
}  # fmt: skip
_WHITESPACE = re.compile(r"\s+")


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            target = defs[node["$ref"].rsplit("/", 1)[-1]]
            merged = {**_inline_refs(copy.deepcopy(target), defs),
                      **{k: v for k, v in node.items() if k != "$ref"}}  # fmt: skip
            return merged
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _strictify(node: Any, in_properties: bool = False) -> Any:
    """Drop unsupported keywords, require every property, forbid extra ones.

    `in_properties` is true for the mapping of property names, whose keys are field names
    (a field called "title" must survive) and not schema keywords."""
    if isinstance(node, dict):
        if in_properties:
            return {k: _strictify(v) for k, v in node.items()}
        cleaned = {
            k: _strictify(v, in_properties=(k == "properties"))
            for k, v in node.items()
            if k not in _UNSUPPORTED
        }
        if cleaned.get("type") == "object" and "properties" in cleaned:
            cleaned["required"] = list(cleaned["properties"])  # strict mode: all required
            cleaned["additionalProperties"] = False
        return cleaned
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    return node


def provider_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Schema to send to a provider: refs inlined, every property required, no extras allowed,
    unsupported validation keywords removed. Local Pydantic validation still enforces them."""
    raw = model.model_json_schema()
    return _strictify(_inline_refs(raw, raw.get("$defs", {})))


def subschema(schema: dict[str, Any], loc: tuple[str | int, ...]) -> dict[str, Any]:
    """The part of `schema` that describes the value at `loc` (an error location)."""
    node = schema
    for part in loc:
        if isinstance(part, int):
            node = node.get("items", {})
        else:
            node = node.get("properties", {}).get(part, {})
    return node


def value_at(data: Any, loc: tuple[str | int, ...]) -> Any:
    for part in loc:
        data = data[part]
    return data


def set_value_at(data: Any, loc: tuple[str | int, ...], value: Any) -> None:
    for part in loc[:-1]:
        data = data[part]
    data[loc[-1]] = value


def normalize_text(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def cache_key(task: str, schema_version: str, messages: list[Message]) -> str:
    """SHA-256 of (task, schema version, normalized input). Provider and model are not part of
    the key: an identical request costs nothing on rerun whichever provider answered first."""
    payload = json.dumps(
        [task, schema_version, [[m.role, normalize_text(m.content)] for m in messages]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
