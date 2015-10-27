
import os
import time
from SimpleHTTPServer import SimpleHTTPRequestHandler
import SocketServer

from virtwhotest import FakeVirt


class RhevmHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.1)
        base = os.path.dirname(os.path.abspath(__file__))
        if self.path == '/api/clusters':
            with open(os.path.join(base, 'data/rhevm/rhevm_clusters.xml'), 'r') as f:
                self.wfile.write(f.read())
        if self.path == '/api/hosts':
            with open(os.path.join(base, 'data/rhevm/rhevm_hosts.xml'), 'r') as f:
                self.wfile.write(f.read())
        elif self.path == '/api/vms':
            vms = 'data/rhevm/rhevm_vms_%d.xml' % self.server._data_version.value
            with open(os.path.join(base, vms), 'r') as f:
                self.wfile.write(f.read())


class FakeRhevm(FakeVirt):
    def __init__(self):
        super(FakeRhevm, self).__init__()
        self.server = SocketServer.TCPServer(("localhost", self.port), RhevmHandler)
        self.server._data_version = self._data_version

    def run(self):
        for i in range(100):
            try:
                print "Starting FakeRhevm on port", self.port
                self.server.serve_forever()
                break
            except AssertionError:
                self.clear_port()
        else:
            raise AssertionError("No free port found, starting aborted")
