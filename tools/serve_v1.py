"""V1 offline launcher. Copy admitted local corpus; never read credentials."""
import argparse
import sqlite3
from thesislab.cli import private_output
from thesislab.web_server import main

def launch():
    p=argparse.ArgumentParser()
    p.add_argument("--port",type=int,default=8766)
    p.add_argument("--db",default=".local/v1.sqlite")
    p.add_argument("--seed-local-corpus",action="store_true")
    args=p.parse_args();destination=private_output(args.db)
    if not destination.exists() and args.seed_local_corpus:
        source=private_output(".local/m3-http-test.sqlite")
        if not source.exists():raise SystemExit("Admitted local corpus missing; no fabricated financial fallback.")
        with sqlite3.connect("file:"+str(source)+"?mode=ro",uri=True) as a:
            with sqlite3.connect(destination) as b:a.backup(b)
    argv=["--db",args.db,"--port",str(args.port)]
    if private_output(".local/deepseek-m25/ledger.json").exists():argv.extend(["--model-cache",".local/deepseek-m25"])
    main(argv)

if __name__=="__main__":launch()
