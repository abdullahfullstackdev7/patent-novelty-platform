"""Chart quality check: agreement of the pre-classifier and model cells with human labels.

    uv run --project backend python scripts/evaluate_chart.py --template docs/chart_labels.csv
    # label at least 30 rows by filling the human_status column (disclosed, partial or not_found)
    uv run --project backend python scripts/evaluate_chart.py docs/chart_labels.csv

Prints the agreement, a confusion table and the best threshold pairs from a sweep of the low and
high cut-offs (current values are 0.35 and 0.88).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.pipeline.evaluation import agreement_report, load_labels, sweep_thresholds, write_template  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("labels", type=Path)
    parser.add_argument("--template", action="store_true", help="write an empty labels file and stop")
    args = parser.parse_args()

    if args.template:
        write_template(args.labels)
        print(f"wrote {args.labels}")
        return
    pairs = load_labels(args.labels)
    if len(pairs) < 30:
        sys.exit(f"{len(pairs)} labelled pairs found. Label at least 30 before drawing conclusions.")
    settings = Settings()
    report = agreement_report(pairs, settings)
    for key, value in report.items():
        print(f"{key}: {value:.3f}" if isinstance(value, float) else f"{key}: {value}")
    print("\nbest thresholds (low, high, accuracy, kappa, share sent to the model):")
    for row in sweep_thresholds(pairs, settings)[:5]:
        print(f"  {row.low:.2f} {row.high:.2f}  {row.accuracy:.3f}  {row.kappa:.3f}  {row.llm_share:.2f}")


if __name__ == "__main__":
    main()
