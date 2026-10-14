"""Development entry point; Compose publishes this only on the host loopback."""
import argparse
from .store import Store
from .workspace import Workspace
from .web_server import make_server
from .cli import private_output

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,default=8767)
    p.add_argument('--db',default='.local/agent.sqlite')
    p.add_argument('--container-local',action='store_true')
    args=p.parse_args()
    store=Store(private_output(args.db))
    server=make_server(Workspace(store),args.port,bind_host='0.0.0.0' if args.container_local else '127.0.0.1')
    print(f'ThesisLab: http://127.0.0.1:{args.port}/research',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();store.close()

if __name__=='__main__':main()
