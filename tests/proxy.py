from __future__ import print_function


from six.moves.BaseHTTPServer import BaseHTTPRequestHandler
from six.moves import socketserver
from threading import Thread, Event
import random


class ProxyHandler(BaseHTTPRequestHandler):
    def do_CONNECT(self):
        self.server.path = self.path

    def do_POST(self):
        self.server.path = self.path


class ProxyServer(socketserver.TCPServer):
    allow_reuse_address = True


class Proxy(Thread):
    def __init__(self):
        super(Proxy, self).__init__()
        for i in range(100):
            self._port = random.randint(8000, 9000)
            try:
                self.server = ProxyServer(('localhost', self._port), ProxyHandler)
                break
            except Exception:
                continue
        else:
            raise AssertionError("No free port found, starting aborted")

        self.server.timeout = 1
        self.terminate_event = Event()

    def terminate(self):
        self.terminate_event.set()

    def run(self):
        while not self.terminate_event.is_set():
            self.server.handle_request()

    @property
    def last_path(self):
        return getattr(self.server, 'path', None)

    @property
    def address(self):
        return 'http://127.0.0.1:%d' % self._port
