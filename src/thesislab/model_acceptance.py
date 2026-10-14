"""Persisted request budget for explicitly authorized Understand/Plan acceptance."""
import threading
from .domain import ContractError,encode
from .store import now

class BoundedAcceptanceModel:
    def __init__(self,model,engine,*,limit=14):
        if type(limit) is not int or not 1<=limit<=14:raise ContractError('acceptance_budget_must_be_one_to_fourteen')
        self.model=model;self.engine=engine;self.limit=limit;self.local=threading.local()
        with engine.begin() as c:
            c.exec_driver_sql('CREATE TABLE IF NOT EXISTS model_acceptance_ledger (attempt INTEGER PRIMARY KEY, phase TEXT NOT NULL, payload TEXT NOT NULL)')
            for op in ('UPDATE','DELETE'):
                c.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immutable_model_acceptance_{op.lower()} BEFORE {op} ON model_acceptance_ledger BEGIN SELECT RAISE(ABORT,'append_only_record'); END")

    def request_metadata(self):return self.model.request_metadata()

    def json(self,system,payload):
        if not ('研究助手的 Understand' in system or '你是 Plan 节点' in system):
            raise ContractError('only_understand_and_plan_acceptance_calls_authorized')
        with self.engine.begin() as c:
            c.exec_driver_sql('BEGIN IMMEDIATE')
            import json
            rows=[(r[0],r[1],json.loads(r[2])) for r in c.exec_driver_sql('SELECT attempt,phase,payload FROM model_acceptance_ledger')]
            reservations={i for i,phase,d in rows if phase=='reserved'}
            results={d['reserved_attempt']:d for i,phase,d in rows if phase=='result'}
            # Known pre-send failures consume no actual API request; incomplete or
            # uncertain outcomes reserve capacity so restarts cannot overspend.
            used=len(reservations-set(results))+sum(d.get('request_sent') is not False for d in results.values())
            if used>=self.limit:raise ContractError('fourteen_request_acceptance_budget_exhausted')
            if len(reservations)>=self.limit+6:raise ContractError('acceptance_pre_send_attempt_limit_exhausted')
            attempt=c.exec_driver_sql('SELECT COALESCE(MAX(attempt),0)+1 FROM model_acceptance_ledger').scalar()
            c.exec_driver_sql('INSERT INTO model_acceptance_ledger VALUES (?,?,?)',
                (attempt,'reserved',encode({'at':now(),'scope':'understand_plan_only','request_sent':False})))
        error=None
        try:return self.model.json(system,payload)
        except Exception as exc:
            error=str(exc) if isinstance(exc,ContractError) else type(exc).__name__
            raise
        finally:
            metadata=self.model.request_metadata()
            with self.engine.begin() as c:
                c.exec_driver_sql('BEGIN IMMEDIATE')
                sequence=c.exec_driver_sql('SELECT COALESCE(MAX(attempt),0)+1 FROM model_acceptance_ledger').scalar()
                c.exec_driver_sql('INSERT INTO model_acceptance_ledger VALUES (?,?,?)',
                    (sequence,'result',encode({'reserved_attempt':attempt,'at':now(),'error':error,**metadata})))

    def totals(self):
        import json
        with self.engine.connect() as c:
            rows=[(r[0],json.loads(r[1])) for r in c.exec_driver_sql('SELECT phase,payload FROM model_acceptance_ledger ORDER BY attempt')]
        results=[d for phase,d in rows if phase=='result'];keys=('prompt_tokens','completion_tokens','total_tokens')
        return {'budget_limit':self.limit,'reserved_attempts':sum(p=='reserved' for p,d in rows),
            'actual_requests_sent':sum(d.get('request_sent') is True for d in results),
            'uncertain_transmissions':sum(d.get('request_sent') is None for d in results),
            'known_token_usage':{k:sum(d.get('usage',{}).get(k,0) for d in results if d.get('usage')) for k in keys},
            'requests_without_token_usage':sum(not d.get('usage') for d in results),'completed_receipts':len(results),
            'pending_or_interrupted_reservations':sum(p=='reserved' for p,d in rows)-len(results),
            'known_pre_send_failures':sum(d.get('request_sent') is False for d in results)}
