"""Explicit, sequential real evaluation runner. NEVER run before human approval.

Only three public generic statements are sent. No private documents/SQL values.
Persistent reserved slots survive process failures; no retries or fallback models.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from thesislab.cli import private_output
from thesislab.deepseek import CallBudget, DeepSeekCandidateProvider, DeepSeekFailure
from thesislab.deepseek_transport import HTTPSDeepSeekTransport
from thesislab.deepseek_keychain import read_authorized_key
from thesislab.deepseek_prompt import PROMPTS
from thesislab.research import request_candidate
from thesislab.research_store import ResearchEngine
from thesislab.store import Store
from thesislab.candidate_review import PUBLIC_CASES, render_candidate, review_form, summarize


def write_private(path, value):
    body = json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:out.write(body)
    os.replace(temp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="M2.5 real calls require explicit human budget approval")
    parser.add_argument("--authorize-budget", action="store_true", help="Use ONLY after human approval in this chat")
    parser.add_argument("--max-requests", type=int, default=18)
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--cases", nargs="+", choices=tuple(PUBLIC_CASES), default=["state", "causal", "attribution"])
    parser.add_argument("--prompt-version", choices=tuple(PROMPTS), default="thesislab-candidate-v1")
    parser.add_argument("--run-dir", default=".local/deepseek-m25")
    args = parser.parse_args(argv)
    # Approval check occurs before reading credentials, constructing Store or HTTP.
    if not args.authorize_budget:
        print("Explicit human authorization of model request/output budget required; no calls made.")
        return 2
    budget = CallBudget(args.max_requests, args.max_output_tokens, authorized=True)
    root = private_output(args.run_dir + "/ledger.json").parent
    root.mkdir(exist_ok=True)
    lock = root / "running.lock"
    try:fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print("Evaluation lock exists; stop and review prior process/ledger, do not auto-restart.")
        return 2
    os.close(fd)
    store = None
    try:
        ledger_path = root / "ledger.json"
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
            "created_at": datetime.now(timezone.utc).isoformat(), "max_requests": budget.max_requests,
            "max_output_tokens": budget.max_output_tokens, "reserved_requests": 0,
            "attempts": [], "halted": False}
        if (ledger["max_requests"], ledger["max_output_tokens"]) != (budget.max_requests, budget.max_output_tokens):
            raise DeepSeekFailure("cannot_increase_or_change_existing_budget")
        if ledger["halted"]:raise DeepSeekFailure("prior_run_halted_requires_review_not_retry")
        if ledger["reserved_requests"] + len(args.cases) > budget.max_requests:
            raise DeepSeekFailure("selected_cases_exceed_remaining_budget")
        # A crash can reserve a slot without a completion. Do not replay it.
        if any(a.get("state") == "reserved" for a in ledger["attempts"]):
            raise DeepSeekFailure("unfinished_attempt_requires_human_review")
        budget.used = ledger["reserved_requests"]
        def reserve(number):
            ledger["reserved_requests"] = number
            ledger["attempts"].append({"request_number": number, "state": "reserved"})
            write_private(ledger_path, ledger)  # Persist BEFORE an HTTP attempt.
        budget.on_consume = reserve
        prompt = PROMPTS[args.prompt_version]
        write_private(root / (args.prompt_version + ".prompt.txt"), prompt)
        provider = DeepSeekCandidateProvider(budget, transport=HTTPSDeepSeekTransport(read_authorized_key),
                                            system_prompt=prompt, prompt_version=args.prompt_version,
                                            character_map=args.prompt_version != "thesislab-candidate-v1")
        store = Store(root / "candidates.sqlite")
        engine = ResearchEngine(store)
        for case in args.cases:
            statement = PUBLIC_CASES[case]
            candidate = None
            try:
                candidate = request_candidate(statement, provider, authorized=True)
            except DeepSeekFailure:
                pass  # Explicit next selected case only; no automatic repair request.
            attempt = dict(provider.attempts[-1])
            attempt["case"] = case
            attempt["state"] = "completed"
            number = attempt["request_number"]
            prefix = root / f"attempt-{number}-{case}"
            if candidate is not None:
                write_private(prefix.with_suffix(".candidate.json"), candidate)
                write_private(prefix.with_suffix(".review.md"), render_candidate(candidate))
                attempt["draft_id"] = engine.draft("deepseek-m25-" + case, candidate, origin="model_candidate")
            elif provider.last_content is not None:
                # Public-statement-only model text, quarantined and never Evidence.
                write_private(prefix.with_suffix(".rejected.txt"), provider.last_content)
            write_private(prefix.with_suffix(".semantic-review.json"), review_form(statement, attempt))
            ledger["attempts"][-1] = attempt
            ledger["halted"] = provider.halted
            write_private(ledger_path, ledger)
            if provider.halted:break
        summary = summarize(ledger["attempts"])
        write_private(root / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (DeepSeekFailure, OSError, ValueError, KeyError) as exc:
        print("Evaluation stopped:", str(exc) if isinstance(exc, DeepSeekFailure) else type(exc).__name__)
        return 1
    finally:
        if store:store.close()
        lock.unlink(missing_ok=True)


if __name__ == "__main__":raise SystemExit(main())
