"""Serve only the demo directory on localhost. No model/GPU dependencies."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __name__ == '__main__':
    folder = Path(__file__).resolve().parents[1] / 'demo'
    server = ThreadingHTTPServer(('127.0.0.1', 8765), partial(SimpleHTTPRequestHandler, directory=str(folder)))
    print('KVRouteBench demo: http://127.0.0.1:8765 — Ctrl+C to stop', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
