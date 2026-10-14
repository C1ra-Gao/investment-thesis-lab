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
    parser = argparse.ArgumentParser(prog="thesislab", description="Local evidence and thesis verification (no network)")
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
    draft = commands.add_parser("draft", help="Import a human-authored or externally produced candidate; not AI parsing")
    draft.add_argument("--input", required=True)
    draft.add_argument("--thesis", required=True)
    draft.add_argument("--origin", choices=("manual", "model_candidate", "synthetic_test"), default="manual")
    draft.add_argument("--parent-confirmation")
    draft.add_argument("--reason")
    confirm = commands.add_parser("confirm")
    confirm.add_argument("--draft", required=True)
    confirm.add_argument("--reviewer", required=True)
    confirm.add_argument("--meaning-reviewed", action="store_true")
    confirm.add_argument("--accept-suggestion", action="append", default=[])
    run = commands.add_parser("evaluate")
    run.add_argument("--confirmation", required=True)
    run.add_argument("--bindings", required=True)
    run.add_argument("--reviewer", required=True)
    run.add_argument("--as-of", required=True)
    check = commands.add_parser("check-condition")
    check.add_argument("--confirmation", required=True)
    check.add_argument("--condition", required=True)
    check.add_argument("--reviewer", required=True)
    check.add_argument("--observed-on", required=True)
    check.add_argument("--evidence")
    check.add_argument("--event", choices=("true", "false"))
    check.add_argument("--reason")
    show = commands.add_parser("research-show")
    show.add_argument("--id")
    show.add_argument("--thesis")
    show.add_argument("--output", default=".local/research.json")
    for p in (draft, confirm, run, check, show):p.add_argument("--db", default=".local/thesislab.sqlite")
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
        elif args.command == "restore":
            output = private_output(args.output)
            result = store.restore(args.task)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({"restored": True, "state": result["state"],
                              "conflicts": len(result["conflicts"]), "assessments": len(result["assessments"])}, ensure_ascii=False))
        else:
            from .research_store import ResearchEngine
            engine = ResearchEngine(store)
            if args.command == "draft":
                data = json.loads(Path(args.input).read_text())
                result_id = engine.draft(args.thesis, data, origin=args.origin,
                                         parent_id=args.parent_confirmation, reason=args.reason)
            elif args.command == "confirm":
                result_id = engine.confirm(args.draft, reviewer=args.reviewer,
                    meaning_reviewed=args.meaning_reviewed, accepted_suggestions=args.accept_suggestion,
                    budget={"llm_calls": 0, "financial_calls": 0})
            elif args.command == "evaluate":
                result_id = engine.evaluate(args.confirmation, json.loads(Path(args.bindings).read_text()),
                                            reviewer=args.reviewer, as_of=args.as_of)
            elif args.command == "check-condition":
                result_id = engine.check_condition(args.confirmation, args.condition, reviewer=args.reviewer,
                    observed_on=args.observed_on, evidence_id=args.evidence,
                    event_occurred=None if args.event is None else args.event == "true", reason=args.reason)
            else:
                if bool(args.id) == bool(args.thesis):raise ContractError("select_one_record_or_thesis")
                result = engine.get(args.id) if args.id else engine.history(args.thesis)
                private_output(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
                print("Research snapshot/history restored to ignored local output.")
                return 0
            print(json.dumps({"saved": True, "id": result_id}))
        return 0
    except (ContractError, KeyError, OSError, ValueError, TypeError, SQLAlchemyError) as exc:
        # Never dump input files, financial values or an uncontrolled traceback to stdout.
        print("Local command failed:", type(exc).__name__, str(exc) if isinstance(exc, ContractError) else "")
        return 1
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
