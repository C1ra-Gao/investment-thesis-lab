"""Local product entry: historical Fuyao tools enabled; all live providers disabled."""
import argparse
from thesislab.cli import private_output
from thesislab.fuyao import HistoricalSnapshot,FuyaoHistoricalProvider
from thesislab.financial_tools import FinancialTools
from thesislab.store import Store
from thesislab.workspace import Workspace
from thesislab.web_server import make_server

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8768)
    p.add_argument('--db',default='.local/m4-workspace.sqlite')
    args=p.parse_args()
    source=private_output('.local/m3-http-test.sqlite')
    if not source.exists():raise SystemExit('Approved project-local financial history missing.')
    snapshot=HistoricalSnapshot.from_database(source)
    tools=FinancialTools({'fuyao':FuyaoHistoricalProvider(snapshot)})
    store=Store(private_output(args.db));ws=Workspace(store)
    server=make_server(ws,args.port,financial_tools=tools)
    print(f'ThesisLab M4 Workspace: http://127.0.0.1:{server.server_port} — historical finance only; live APIs and models disabled.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();store.close()

if __name__=='__main__':main()
