from __future__ import print_function

import time

from fake_virt import FakeVirt, FakeHandler


class NutanixHandler(FakeHandler):
    def do_GET(self):
        time.sleep(0.1)
        print(("DO GET", self.path))

        if self.path == '/PrismGateway/services/rest/v2.0/clusters':
            self.write_file('nutanix', 'clusters.json')
        elif self.path == '/PrismGateway/services/rest/v2.0/hosts':
            self.write_file('nutanix', 'hosts.json')
        elif self.path == '/PrismGateway/services/rest/v2.0/vms':
            self.write_file('nutanix', 'vms.json')
        else:
            self.send_response(404)
            self.end_headers()

class FakeNutanix(FakeVirt):
    def __init__(self, port=None):
        super(FakeNutanix, self).__init__(NutanixHandler, port=port)
        self.server._data_version = self._data_version

if __name__ == '__main__':
    nutanix = FakeNutanix(port=9440)
    nutanix.run()
