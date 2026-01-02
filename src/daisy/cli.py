from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .agent import validate


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="daisy", description="DAC review agent (no UI).")

    sub = parser.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate a DAC PDF and evidence exports.")
    v.add_argument("--dac", required=True, type=Path, help="Path to DAC PDF.")
    v.add_argument("--evidence-dir", required=True, type=Path, help="Directory containing evidence XLSX/PDF exports.")
    v.add_argument("--out", type=Path, default=Path("out"), help="Output directory for review_result.json/md")
    v.add_argument("--print", dest="print_json", action="store_true", help="Print JSON to stdout.")

    v.add_argument(
        "--lenient",
        action="store_true",
        help="Missing DAC yes/no fields become SKIPPED (useful if PDF cannot be edited).",
    )
    v.add_argument(
        "--mvp",
        action="store_true",
        help="MVP mode: tolerate small master-data gaps and skip non-critical evidence (still reported as warnings).",
    )

    v.add_argument(
        "--rules",
        type=Path,
        default=Path("config/rules.yaml"),
        help="Path to rules YAML (default: config/rules.yaml).",
    )

    args = parser.parse_args(argv)

    if args.cmd == "validate":
        res = validate(
            args.dac,
            args.evidence_dir,
            out_dir=args.out,
            lenient=args.lenient,
            mvp=args.mvp,
            rules_path=args.rules,
        )
        if args.print_json:
            print(json.dumps(res.to_dict(), indent=2))


if __name__ == "__main__":
    main()
