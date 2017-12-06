from __future__ import print_function

import time

from fake_virt import FakeVirt, FakeHandler


class Rhevm4Handler(FakeHandler):
    def do_GET(self):
        time.sleep(0.1)
        print(("DO GET", self.path))

        if self.path == '/ovirt-engine/api':
            self.write_file('rhevm', 'rhev4_api.xml')
        elif self.path == '/ovirt-engine/api/clusters':
            self.check_version_header()
            self.write_file('rhevm', 'rhevm_clusters.xml')
        elif self.path == '/ovirt-engine/api/hosts':
            self.check_version_header()
            self.write_file('rhevm', 'rhevm_hosts.xml')
        elif self.path == '/ovirt-engine/api/vms':
            self.check_version_header()
            self.write_file('rhevm', 'rhevm_vms_%d.xml' % self.server._data_version.value)
        else:
            self.send_response(404)
            self.end_headers()

    def check_version_header(self):
        if not self.headers['Version'] == '3':
            self.send_response(400, 'Version header mismatch')


class FakeRhevm4(FakeVirt):
    def __init__(self, port=None):
        super(FakeRhevm4, self).__init__(Rhevm4Handler, port=port)
        self.server._data_version = self._data_version

if __name__ == '__main__':
    rhevm = FakeRhevm4(port=8443)
    rhevm.run()
