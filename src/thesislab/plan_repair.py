"""One bounded internal format repair; never rewrite semantics or weaken M2 checks."""
from copy import deepcopy
from .domain import ContractError
from .research import validate_draft

def prepare_candidate(design,original):
    if not isinstance(design,dict) or design.get('statement')!=original:
        raise ContractError('provider_changed_original_statement')
    try:return validate_draft(design),[]
    except (ContractError,TypeError,KeyError,ValueError):pass
    repaired=deepcopy(design);changes=[]
    # Only a literal span occurring exactly once has a provable index correction.
    # No text insertion, node/task deletion, relation change, or inferred source.
    for claim in repaired.get('claims',[]):
        if not isinstance(claim,dict):continue
        for index,span in enumerate(claim.get('spans',[])):
            if not isinstance(span,dict):continue
            text=span.get('text');a,b=span.get('start'),span.get('end')
            if not isinstance(text,str) or not text or original.count(text)!=1:continue
            start=original.index(text);end=start+len(text)
            if type(a) is int and type(b) is int and (a,b)!=(start,end):
                changes.append({'claim_id':claim.get('id'),'span_index':index,'before':{'start':a,'end':b},'after':{'start':start,'end':end},'reason':'unique_exact_original_substring'})
                span.update(start=start,end=end)
    return validate_draft(repaired),changes
