"""Offline HTTP/browser QA server: explicitly replay prior real model outputs.

No Keychain, credential loading or external API request. Not a model simulator or
general decomposition capability; only exact previously evaluated statements.
"""

import argparse
import json
from pathlib import Path

from thesislab.cli import private_output
from thesislab.deepseek import CallBudget, DeepSeekCandidateProvider
from thesislab.deepseek_prompt import PROMPTS
from thesislab.deepseek_transport import TransportResponse
from thesislab.store import Store
from thesislab.workspace import Workspace
from thesislab.web_server import make_server


class RealModelCacheReplay:
    def __init__(self, root):self.root = root
    def send(self, body, *, timeout):
        statement=json.loads(json.loads(body)["messages"][1]["content"])["investment_thesis"]
        ledger=json.loads((self.root/"ledger.json").read_text())
        for receipt in reversed(ledger["attempts"]):
            number,case=receipt["request_number"],receipt["case"]
            path=self.root/f"attempt-{number}-{case}"
            path=path.with_suffix(".candidate.json") if receipt["m2_schema_pass"] else path.with_suffix(".rejected.txt")
            content=path.read_text()
            if json.loads(content)["statement"]==statement:
                envelope={"id":"cache-replay-not-new-model-request","model":receipt["returned_model"],
                    "system_fingerprint":receipt.get("system_fingerprint"),"usage":{},
                    "choices":[{"finish_reason":"stop","message":{"role":"assistant","content":content}}]}
                raw=json.dumps(envelope,ensure_ascii=False).encode()
                return TransportResponse(200,raw,True,len(raw))
        return TransportResponse(422,b"",True,0)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--phase3-root");parser.add_argument("--model-cache",required=True)
    parser.add_argument("--reuse-local-corpus",action="store_true")
    args=parser.parse_args()
    database=private_output(".local/m3-http-test.sqlite")
    if args.reuse_local_corpus and not database.exists():raise ValueError("local_verified_corpus_missing")
    store=Store(database)
    if not args.reuse_local_corpus:
        if not args.phase3_root:raise ValueError("phase3_root_required_for_initial_seed")
        from thesislab.regression import verify_phase3
        verify_phase3(Path(args.phase3_root).resolve(),store)
    cache=private_output(args.model_cache+"/ledger.json").parent
    provider=DeepSeekCandidateProvider(CallBudget(12,12000,True),transport=RealModelCacheReplay(cache),
                                      system_prompt=PROMPTS["thesislab-candidate-v2"],prompt_version="thesislab-candidate-v2",character_map=True)
    workspace=Workspace(store,provider=provider,model_cache=cache,model_mode="real_model_cache_replay_only")
    server=make_server(workspace,args.port)
    print(f"OFFLINE HTTP QA: http://127.0.0.1:{server.server_port}; no model calls or credential reads.",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();store.close()


if __name__=="__main__":main()
