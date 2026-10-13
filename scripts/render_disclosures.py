"""Render a markdown copy next to every dataset/disclosures/*.json file."""

from __future__ import annotations

import json

from _common import DATASET


def render(data: dict) -> str:
    lines = [
        f"# {data['title']}",
        "",
        "Synthetic sample disclosure for demonstration. Not a real invention.",
        "",
        f"- Technical field: {data['technical_field']}",
        f"- Priority date: {data['priority_date']}",
        f"- Jurisdiction: {data['jurisdiction']}",
        "",
        "## Problem",
        "",
        data["problem"],
        "",
        "## Solution",
        "",
        data["solution"],
        "",
        "## Key elements",
        "",
    ]
    lines += [f"{item['id']}. {item['text']}" for item in data["elements"]]
    lines += ["", "## Optional dependent features", ""]
    lines += [f"- {feature}" for feature in data["dependent_features"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    for path in sorted((DATASET / "disclosures").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        path.with_suffix(".md").write_text(render(data), encoding="utf-8", newline="\n")
        print("wrote", path.with_suffix(".md").name)


if __name__ == "__main__":
    main()
