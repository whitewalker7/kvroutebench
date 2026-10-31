"""Local learning router: alternate two workers, preserve streaming, never retry."""

import http.client
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Router(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, workers):
        super().__init__(address, Handler)
        self.workers = workers
        self.next_worker = 0
        self.selection_lock = threading.Lock()

    def select_worker(self):
        # Only selection needs the lock; streaming requests can run concurrently.
        with self.selection_lock:
            worker = self.workers[self.next_worker]
            self.next_worker = (self.next_worker + 1) % len(self.workers)
        return worker


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 closes each downstream connection, framing unknown-length streams.
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","scope":"router only"}\n')

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        if self.headers.get("Transfer-Encoding"):
            self.send_error(400, "Send a Content-Length body")
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 < length <= 1024 * 1024:
                raise ValueError()
            self.connection.settimeout(120)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError()
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get("stream") is not True:
                raise ValueError()
        except (ValueError, OSError):
            self.send_error(400, "Expected streamed JSON request, at most 1 MiB")
            return

        host, port = self.server.select_worker()
        worker = f"http://{host}:{port}"
        route_id = uuid.uuid4().hex
        upstream = http.client.HTTPConnection(host, port, timeout=120)
        headers_sent = False
        log = {"route_id": route_id, "worker": worker, "attempts": 1}
        try:
            upstream.request("POST", self.path, body=body,
                             headers={"Content-Type": "application/json"})
            response = upstream.getresponse()
            log["status"] = response.status
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/octet-stream"))
            self.send_header("X-Router-Worker", worker)
            self.send_header("X-Router-Request-Id", route_id)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            headers_sent = True
            # Forward each SSE line immediately, including blank event separators.
            # Do not wait for the entire answer or a large fixed-size buffer.
            for line in response:
                self.wfile.write(line)
                self.wfile.flush()
        except (OSError, http.client.HTTPException) as error:
            log["error"] = str(error)
            if not headers_sent:
                self.send_error(502, "Selected worker unavailable; no retry")
            # After headers, close a failed stream; client detects missing DONE.
        finally:
            upstream.close()
            self.close_connection = True
            print(json.dumps(log), flush=True)


if __name__ == "__main__":
    server = Router(("127.0.0.1", 8000), [("127.0.0.1", 8001), ("127.0.0.1", 8002)])
    print("Round-robin router ready: 127.0.0.1:8000 -> workers 8001, 8002", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
