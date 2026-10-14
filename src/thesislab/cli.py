"""Local commands only. Runtime databases and reports must live in .local/."""

import argparse
import json
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError

from .domain import ContractError
from .store import Store


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def private_output(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to((PROJECT_ROOT / ".local").resolve()):
        raise ContractError("runtime_outputs_must_be_inside_project_local_directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="thesislab", description="M1 local evidence verification (no network)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-db")
    init.add_argument("--db", default=".local/thesislab.sqlite")
    regression = commands.add_parser("regress")
    regression.add_argument("--phase3-root", required=True)
    regression.add_argument("--db", default=".local/regression.sqlite")
    regression.add_argument("--output", default=".local/regression.json")
    restore = commands.add_parser("restore")
    restore.add_argument("--db", default=".local/regression.sqlite")
    restore.add_argument("--task", default="internal-regression")
    restore.add_argument("--output", default=".local/restored.json")
    trace = commands.add_parser("trace")
    trace.add_argument("--db", default=".local/regression.sqlite")
    trace.add_argument("--evidence", required=True)
    trace.add_argument("--output", default=".local/evidence-chain.json")
    review = commands.add_parser("review")
    review.add_argument("--db", default=".local/regression.sqlite")
    review.add_argument("--conflict", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--reason", required=True)
    review.add_argument("--selected-evidence")
    review.add_argument("--field", choices=("original_disclosure_date", "value", "scope"))
    review.add_argument("--resolve", action="store_true", help="Only for a fully resolved non-date conflict")
    args = parser.parse_args(argv)
    store = None
    try:
        db = private_output(args.db)
        if args.command in ("restore", "trace", "review") and not db.exists():
            raise ContractError("database_does_not_exist")
        store = Store(db)
        if args.command == "init-db":
            print("Local schema v1 initialized; no credentials or network used.")
        elif args.command == "regress":
            from .regression import verify_phase3
            root = Path(args.phase3_root).resolve()
            if root.is_relative_to(PROJECT_ROOT):
                raise ContractError("real_source_material_must_stay_outside_project")
            output = private_output(args.output)
            result = verify_phase3(root, store)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({k: result[k] for k in ("input_kind", "source_fields_matched", "official_reports",
                              "conflict_count", "unresolved_conflicts", "financial_requests", "keychain_reads")}, ensure_ascii=False))
            print("Detailed evidence stays in ignored .local outputs.")
        elif args.command == "review":
            sequence = store.review(args.conflict, reviewer=args.reviewer, reason=args.reason,
                                    selected_evidence_id=args.selected_evidence, field=args.field,
                                    keep_unresolved=not args.resolve)
            print(json.dumps({"review_saved": True, "sequence": sequence,
                              "state": store.conflict_state(args.conflict)["state"]}))
        elif args.command == "trace":
            output = private_output(args.output)
            result = store.trace(args.evidence)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print("Evidence lineage saved locally; no financial values printed.")
        else:
            output = private_output(args.output)
            result = store.restore(args.task)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({"restored": True, "state": result["state"],
                              "conflicts": len(result["conflicts"]), "assessments": len(result["assessments"])}, ensure_ascii=False))
        return 0
    except (ContractError, KeyError, OSError, ValueError, SQLAlchemyError) as exc:
        # Never dump input files, financial values or an uncontrolled traceback to stdout.
        print("M1 command failed:", type(exc).__name__)
        return 1
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
