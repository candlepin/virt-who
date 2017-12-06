from __future__ import print_function

import time

from fake_virt import FakeVirt, FakeHandler


class RhevmHandler(FakeHandler):
    def do_GET(self):
        time.sleep(0.1)
        print(("DO GET", self.path))
        if self.path == '/api':
            self.write_file('rhevm', 'rhev3_api.xml')
        elif self.path == '/api/clusters':
            self.write_file('rhevm', 'rhevm_clusters.xml')
        elif self.path == '/api/hosts':
            self.write_file('rhevm', 'rhevm_hosts.xml')
        elif self.path == '/api/vms':
            self.write_file('rhevm', 'rhevm_vms_%d.xml' % self.server._data_version.value)


class FakeRhevm(FakeVirt):
    def __init__(self, port=None):
        super(FakeRhevm, self).__init__(RhevmHandler, port=port)
        self.server._data_version = self._data_version

if __name__ == '__main__':
    rhevm = FakeRhevm(port=8443)
    rhevm.run()
