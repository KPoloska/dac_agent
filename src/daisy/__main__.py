from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .agent import validate
from .util import (
    sha256_file,
    evidence_file_list_hash,
    sanitize_json,
)


EXIT_OK = 0
EXIT_PARTIAL = 2
EXIT_NOT_MET = 3
EXIT_ERROR = 4


def _exit_code_for_overall(overall: str) -> int:
    overall_u = (overall or "").strip().upper()
    if overall_u == "MET":
        return EXIT_OK
    if overall_u == "PARTIALLY_MET":
        return EXIT_PARTIAL
    if overall_u == "NOT_MET":
        return EXIT_NOT_MET
    return EXIT_ERROR


def _setup_logging(out_dir: Optional[Path]) -> Optional[Path]:
    log = logging.getLogger()
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    # stderr handler
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    log.addHandler(sh)

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "run.log"
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
        return log_path

    return None


def _schema_validate_best_effort(result_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Best effort schema validation.
    - If jsonschema + schema file exist => validate
    - Otherwise => mark as skipped (not a failure)
    """
    schema_path = Path("config") / "review_result.schema.json"
    if not schema_path.exists():
        return {"validated": False, "error": "schema skipped: schema file not found"}

    try:
        import jsonschema  # type: ignore
    except Exception:
        return {"validated": False, "error": "schema skipped: jsonschema not installed"}

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=result_dict, schema=schema)
        return {"validated": True, "error": None}
    except Exception as e:
        return {"validated": False, "error": f"{type(e).__name__}: {e}"}


def cmd_validate(args: argparse.Namespace) -> int:
    dac = Path(args.dac)
    evidence_dir = Path(args.evidence_dir)
    out_dir = Path(args.out) if args.out else Path("out")
    rules_path = Path(args.rules) if args.rules else None

    log_path = _setup_logging(out_dir)

    # Hard fail early: paths
    if not dac.exists() or not dac.is_file():
        logging.error("DAC PDF not found: %s", dac)
        return EXIT_ERROR
    if not evidence_dir.exists() or not evidence_dir.is_dir():
        logging.error("Evidence dir not found: %s", evidence_dir)
        return EXIT_ERROR
    if rules_path is not None and (not rules_path.exists() or not rules_path.is_file()):
        logging.error("rules.yaml not found: %s", rules_path)
        return EXIT_ERROR

    t0 = time.perf_counter()

    # Reproducibility hashes
    try:
        dac_sha = sha256_file(dac)
    except Exception as e:
        logging.error("Failed hashing DAC: %s", e)
        return EXIT_ERROR

    rules_sha = None
    if rules_path is not None:
        try:
            rules_sha = sha256_file(rules_path)
        except Exception as e:
            logging.error("Failed hashing rules.yaml: %s", e)
            return EXIT_ERROR

    ev_list, ev_list_hash = evidence_file_list_hash(evidence_dir, recursive=False)

    # Run validation
    try:
                result = validate(
            dac_pdf=dac,
            evidence_dir=evidence_dir,
            out_dir=out_dir,
            lenient=bool(args.lenient),
            mvp=bool(args.mvp),
            rules_path=rules_path,
            ocr=bool(getattr(args, "ocr", False)),
            ocr_lang=str(getattr(args, "ocr_lang", "eng")),
            tesseract_cmd=getattr(args, "tesseract_cmd", None),
            ocr_max_pages=getattr(args, "ocr_max_pages", None),
            ocr_dpi=int(getattr(args, "ocr_dpi", 200)),
        )
    except Exception as e:
        logging.exception("Runtime error during validate(): %s", e)
        # write minimal run_summary
        _write_run_summary(
            out_dir=out_dir,
            payload={
                "result_version": "1.0",
                "dac_file": str(dac),
                "evidence_dir": str(evidence_dir),
                "rules_path": str(rules_path) if rules_path else None,
                "flags": {"mvp": bool(args.mvp), "lenient": bool(args.lenient), "schema_validate": not bool(args.schema_off)},
                "timings_sec": {"total": float(time.perf_counter() - t0)},
                "schema": {"validated": False, "error": f"runtime_error: {type(e).__name__}: {e}"},
                "output_files": {
                    "review_result_json": str(out_dir / "review_result.json"),
                    "review_result_md": str(out_dir / "review_result.md"),
                    "run_summary_json": str(out_dir / "run_summary.json"),
                    "run_log": str(log_path) if log_path else None,
                },
            },
        )
        return EXIT_ERROR

    total_sec = float(time.perf_counter() - t0)

    # Read back the written review_result.json (already sanitized by agent.py)
    review_path = out_dir / "review_result.json"
    try:
        review_dict = json.loads(review_path.read_text(encoding="utf-8"))
    except Exception as e:
        logging.error("Failed reading review_result.json: %s", e)
        return EXIT_ERROR

    # Schema validation (best-effort) unless disabled
    schema_info = {"validated": False, "error": "schema disabled by --schema-off"} if args.schema_off else _schema_validate_best_effort(review_dict)

    # If schema actually ran and failed => exit 4
    if (not args.schema_off) and schema_info.get("validated") is False:
        # only treat as failure if it wasn't a “skipped” case
        err = (schema_info.get("error") or "")
        if not err.startswith("schema skipped:"):
            logging.error("Schema validation failed: %s", err)
            exit_code = EXIT_ERROR
        else:
            exit_code = _exit_code_for_overall(result.overall_status)
    else:
        exit_code = _exit_code_for_overall(result.overall_status)

    # OCR-required list
    ocr_required_files = []
    try:
        for sec in result.sections:
            for chk in sec.checks:
                ev = chk.evidence or {}
                if isinstance(ev, dict) and ev.get("ocr_required") is True:
                    # file might be "daisy_test_data\\Chapter1.pdf"
                    f = ev.get("file")
                    if isinstance(f, str):
                        ocr_required_files.append(Path(f).name)
    except Exception:
        pass
    ocr_required_files = sorted(set(ocr_required_files))

    # Counts
    checks_count = sum(len(s.checks) for s in result.sections)
    referenced_xlsx = []
    try:
        referenced_xlsx = list((result.stats or {}).get("referenced_xlsx") or [])
    except Exception:
        referenced_xlsx = []

    run_summary = {
        "result_version": "1.0",
        "dac_file": str(dac),
        "evidence_dir": str(evidence_dir),
        "rules_path": str(rules_path) if rules_path else None,
        "flags": {
            "mvp": bool(args.mvp),
            "lenient": bool(args.lenient),
            "schema_validate": not bool(args.schema_off),
        },
        "timings_sec": {"total": total_sec},
        "counts": {
            "sections": len(result.sections),
            "checks": int(checks_count),
            "referenced_xlsx": int(len(referenced_xlsx)),
            "ocr_required_pdfs": int(len(ocr_required_files)),
        },
        "ocr_required_files": ocr_required_files,
        "ocr": bool(args.ocr),
        "ocr_lang": str(args.ocr_lang),
        "ocr_max_pages": args.ocr_max_pages,
        "ocr_dpi": int(args.ocr_dpi),
        "inputs": {
            "sha256": {
                "dac_pdf": dac_sha,
                "rules_yaml": rules_sha,
                "evidence_file_list": ev_list_hash,
            },
            "evidence_file_list": ev_list,
        },
        "schema": schema_info,
        "output_files": {
            "review_result_json": str(out_dir / "review_result.json"),
            "review_result_md": str(out_dir / "review_result.md"),
            "run_summary_json": str(out_dir / "run_summary.json"),
            "run_log": str(log_path) if log_path else None,
        },
    }

    _write_run_summary(out_dir, run_summary)

    # One-line summary (CI friendly)
    print(
        f"OVERALL={result.overall_status} exit={exit_code} "
        f"sections={len(result.sections)} checks={checks_count} "
        f"ocr_required={len(ocr_required_files)} out={out_dir}",
        flush=True,
    )

    # Optional: print markdown report to stdout
    if args.print:
        md_path = out_dir / "review_result.md"
        if md_path.exists():
            print(md_path.read_text(encoding="utf-8"), flush=True)

    return exit_code


def _write_run_summary(out_dir: Path, payload: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "run_summary.json"
    clean = sanitize_json(payload)
    p.write_text(json.dumps(clean, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="daisy", description="Daisy DAC validation CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate a DAC PDF against evidence exports")
    p_val.add_argument("--dac", required=True, help="Path to DAC PDF")
    p_val.add_argument("--evidence-dir", required=True, help="Path to evidence directory")
    p_val.add_argument("--out", default="out", help="Output directory (default: out)")
    p_val.add_argument("--rules", default="config/rules.yaml", help="Path to rules.yaml (default: config/rules.yaml)")
    p_val.add_argument("--lenient", action="store_true", help="Lenient mode: missing yes/no becomes SKIPPED")
    p_val.add_argument("--mvp", action="store_true", help="MVP mode: tolerances + some skips")
    p_val.add_argument("--print", action="store_true", help="Print markdown report to stdout after run")
    p_val.add_argument("--schema-off", action="store_true", help="Disable schema validation")
    # OCR (optional)
    p_val.add_argument("--ocr", action="store_true", help="Attempt OCR on scanned/image-based evidence PDFs")
    p_val.add_argument("--ocr-lang", default="eng", help="Tesseract language (default: eng)")
    p_val.add_argument("--tesseract-cmd", default=None, help="Path to tesseract.exe (optional)")
    p_val.add_argument("--ocr-max-pages", type=int, default=None, help="Max pages to OCR per PDF (optional)")
    p_val.add_argument("--ocr-dpi", type=int, default=200, help="DPI for rendering pages before OCR (default: 200)")


    args = parser.parse_args(argv)

    if args.cmd == "validate":
        return cmd_validate(args)

    print("Unknown command", file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
