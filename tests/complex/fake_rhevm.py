
import time

from fake_virt import FakeVirt, FakeHandler


class RhevmHandler(FakeHandler):
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
    def __init__(self, port=None):
        super(FakeRhevm, self).__init__(RhevmHandler, port=port)
        self.server._data_version = self._data_version

if __name__ == '__main__':
    rhevm = FakeRhevm(port=8443)
    rhevm.run()
