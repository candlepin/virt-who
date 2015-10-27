
import os
import tempfile
from SimpleHTTPServer import SimpleHTTPRequestHandler
from multiprocessing import Process
import SocketServer
import ssl
import json
import random

from manager.subscriptionmanager.subscriptionmanager import rhsm_config


class SamHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/status'):
            self.wfile.write(json.dumps({
                "result": "ok",
                "managerCapabilities": [""]
            }))

    def do_POST(self):
        if self.path.startswith('/hypervisors'):
            size = int(self.headers["Content-Length"])
            data = json.loads(self.rfile.read(size))
            self.server.sam.association.clear()
            self.server.sam.association.update(data)
            self.wfile.write(json.dumps({
                "failedUpdate": [],
                "updated": [],
                "created": [],
            }))


class FakeSam(Process):
    def __init__(self, association):
        super(FakeSam, self).__init__()
        self.daemon = True
        self._port = None
        self.server = SocketServer.TCPServer(("localhost", self.port), SamHandler)
        base = os.path.dirname(os.path.abspath(__file__))
        self.server.socket = ssl.wrap_socket(self.server.socket, certfile=os.path.join(base, 'server.pem'), keyfile=os.path.join(base, 'key.pem'), server_side=True)
        self.config = tempfile.NamedTemporaryFile()
        self.config.write("""
[server]
hostname = localhost
prefix = /
port = %s
insecure = 1
""" % self.port)
        self.config.seek(0)
        rhsm_config.DEFAULT_CONFIG_PATH = self.config.name
        rhsm_config.DEFAULT_HOSTNAME = 'localhost'

        self.server.sam = self
        self.association = association

    @property
    def port(self):
        if self._port is None:
            self._port = random.randint(8000, 9000)
        return self._port

    def clear_port(self):
        print "Clear port: ", self._port
        self._port = None

    def run(self):
        for i in range(100):
            try:
                print "Starting FakeSam on port", self.port
                self.server.serve_forever()
                break
            except AssertionError:
                self.clear_port()
        else:
            raise AssertionError("No free port found, starting aborted")

    def terminate(self):
        self.config.close()
        super(FakeSam, self).terminate()

if __name__ == '__main__':
    server = SocketServer.TCPServer(("localhost", 8443), SamHandler)
    base = os.path.dirname(os.path.abspath(__file__))
    server.socket = ssl.wrap_socket(server.socket, certfile=os.path.join(base, 'server.pem'), keyfile=os.path.join(base, 'key.pem'), server_side=True)
    server.serve_forever()
