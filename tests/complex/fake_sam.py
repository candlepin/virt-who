
import os
import tempfile
from SimpleHTTPServer import SimpleHTTPRequestHandler
import ssl
import json
import shutil

from manager.subscriptionmanager.subscriptionmanager import rhsm_config
from fake_virt import FakeVirt, FakeHandler


class SamHandler(FakeHandler):
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
            self.server.queue.put(data)
            self.wfile.write(json.dumps({
                "failedUpdate": [],
                "updated": [],
                "created": [],
            }))



class FakeSam(FakeVirt):
    def __init__(self, queue, port=None):
        super(FakeSam, self).__init__(SamHandler, port=port)
        self.daemon = True
        base = os.path.dirname(os.path.abspath(__file__))
        self.server.socket = ssl.wrap_socket(self.server.socket, certfile=os.path.join(base, 'cert.pem'), keyfile=os.path.join(base, 'key.pem'), server_side=True)

        self.tempdir = tempfile.mkdtemp()
        config_name = os.path.join(self.tempdir, 'rhsm.conf')
        with open(config_name, 'w') as f:
            f.write("""
[server]
hostname = localhost
prefix = /
port = %s
insecure = 1

[rhsm]
consumerCertDir = %s
""" % (self.port, base))

        rhsm_config.DEFAULT_CONFIG_PATH = config_name

        self.server.sam = self
        self.server.queue = queue

    def terminate(self):
        shutil.rmtree(self.tempdir)
        super(FakeSam, self).terminate()

if __name__ == '__main__':
    server = SocketServer.TCPServer(("localhost", 8443), SamHandler)
    base = os.path.dirname(os.path.abspath(__file__))
    server.socket = ssl.wrap_socket(server.socket, certfile=os.path.join(base, 'server.pem'), keyfile=os.path.join(base, 'key.pem'), server_side=True)
    server.serve_forever()
