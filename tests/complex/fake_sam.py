
import os
import sys
import tempfile
import ssl
import json
import shutil

from fake_virt import FakeVirt, FakeHandler

from virtwho.manager.subscriptionmanager.subscriptionmanager import rhsm_config


class SamHandler(FakeHandler):
    def do_GET(self):
        print "[FakeSam] GET", self.path
        if self.path.startswith('/status'):
            self.wfile.write(json.dumps({
                "result": "ok",
                "managerCapabilities": [""]
            }))
        else:
            self.wfile.write(json.dumps({
                "result": "ok",
            }))

    def do_POST(self):
        print "[FakeSam] POST", self.path
        if self.server.code:
            self.send_response(self.server.code)
            self.send_header("Retry-After", "60")
            self.wfile.write(json.dumps({}))
        elif self.path.startswith('/hypervisors'):
            size = int(self.headers["Content-Length"])
            data = json.loads(self.rfile.read(size))
            print "[FakeSam] putting in the queue:", data
            self.server.queue.put(data)
            self.wfile.write(json.dumps({
                "failedUpdate": [],
                "updated": [],
                "created": [],
            }))

    def do_PUT(self):
        print "PUT", self.path


class FakeSam(FakeVirt):
    def __init__(self, queue, port=None, code=None, host='localhost'):
        super(FakeSam, self).__init__(SamHandler, port=port, host=host)
        self.daemon = True
        self.server.code = code
        base = os.path.dirname(os.path.abspath(__file__))
        certfile = os.path.join(base, 'cert.pem')
        keyfile = os.path.join(base, 'key.pem')
        if not os.access(certfile, os.R_OK):
            raise OSError("No such file %s" % certfile)
        if not os.access(keyfile, os.R_OK):
            raise OSError("No such file %s" % keyfile)
        self.server.socket = ssl.wrap_socket(self.server.socket, certfile=certfile, keyfile=keyfile, server_side=True)

        self.tempdir = tempfile.mkdtemp()
        config_name = os.path.join(self.tempdir, 'rhsm.conf')
        with open(config_name, 'w') as f:
            f.write("""
[server]
hostname = localhost
prefix = /
port = {port}
insecure = 1
proxy_hostname =

[rhsm]
consumerCertDir = {certdir}
""".format(port=self.port, certdir=base))

        rhsm_config.DEFAULT_CONFIG_PATH = config_name

        self.server.sam = self
        self.server.queue = queue

    def terminate(self):
        shutil.rmtree(self.tempdir)
        super(FakeSam, self).terminate()

if __name__ == '__main__':
    if len(sys.argv) >= 2:
        code = int(sys.argv[1])
    else:
        code = None
    from Queue import Queue
    q = Queue()
    f = FakeSam(q, port=8443, code=code, host='0.0.0.0')
    f.run()
