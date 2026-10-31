"""Loopback integration checks using fake workers, never the model servers."""

import http.client
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from routerbench.round_robin import Router


BODY = b'{"stream":true,"messages":[]}'
FIRST = b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
TAIL = b'data: {"usage":{"prompt_tokens_details":{"cached_tokens":7}}}\n\ndata: [DONE]\n\n'


class FakeWorker(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.received.append(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(self.server.status)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        self.wfile.write(FIRST)
        self.wfile.flush()
        self.server.release.wait(5)
        self.wfile.write(TAIL)


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.servers = []
        self.threads = []
        for _ in range(2):
            server = ThreadingHTTPServer(('127.0.0.1', 0), FakeWorker)
            server.received = []
            server.status = 200
            server.release = threading.Event()
            server.release.set()
            self.start(server)
        self.workers = self.servers[:]
        self.router = Router(('127.0.0.1', 0), [s.server_address for s in self.workers])
        self.start(self.router)

    def start(self, server):
        self.servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.threads.append(thread)

    def tearDown(self):
        for worker in self.workers:
            worker.release.set()
        for server in reversed(self.servers):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()

    def request(self):
        conn = http.client.HTTPConnection(*self.router.server_address, timeout=2)
        conn.request('POST', '/v1/chat/completions', BODY,
                     {'Content-Type': 'application/json'})
        return conn, conn.getresponse()

    def test_alternates_and_preserves_body_stream_usage_and_identity(self):
        for index in (0, 1, 0, 1):
            conn, response = self.request()
            try:
                self.assertEqual(response.status, 200)
                host, port = self.workers[index].server_address
                self.assertEqual(response.getheader('X-Router-Worker'), f'http://{host}:{port}')
                self.assertTrue(response.getheader('X-Router-Request-Id'))
                self.assertEqual(response.read(), FIRST + TAIL)
            finally:
                conn.close()
        for worker in self.workers:
            self.assertEqual(worker.received, [BODY, BODY])

    def test_first_content_arrives_before_worker_finishes(self):
        self.workers[0].release.clear()
        conn, response = self.request()
        try:
            self.assertEqual(response.readline(), FIRST.splitlines(keepends=True)[0])
            self.assertFalse(self.workers[0].release.is_set())
        finally:
            self.workers[0].release.set()
            response.read()
            conn.close()

    def test_upstream_error_is_preserved_without_retry(self):
        self.workers[0].status = 503
        conn, response = self.request()
        try:
            self.assertEqual(response.status, 503)
            response.read()
            self.assertEqual(len(self.workers[0].received), 1)
            self.assertEqual(len(self.workers[1].received), 0)
        finally:
            conn.close()
