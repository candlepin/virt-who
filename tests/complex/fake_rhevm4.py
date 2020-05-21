from __future__ import print_function

#
# Module for abstraction of all virtualization backends, part of virt-who
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

import sys
import time

from fake_virt import FakeVirt
from fake_server import FakeHandler


class Rhevm4Handler(FakeHandler):
    def do_GET(self):
        time.sleep(0.1)
        print(("[RHEVM] DO GET", self.path))

        if self.path == '/ovirt-engine/api':
            self.write_file('rhevm', 'rhev4_api.xml')
        elif self.path == '/ovirt-engine/api/clusters':
            self.write_file('rhevm', 'rhevm_clusters.xml')
        elif self.path == '/ovirt-engine/api/hosts':
            self.write_file('rhevm', 'rhevm_hosts.xml')
        elif self.path == '/ovirt-engine/api/vms':
            self.write_file('rhevm', 'rhevm_vms_%d.xml' % self.server._data_version.value)
        else:
            self.send_response(404)
            self.end_headers()


class FakeRhevm4(FakeVirt):

    virt_type = "rhevm"

    def __init__(self, port=None):
        super(FakeRhevm4, self).__init__(Rhevm4Handler, port=port)
        self.server._data_version = self._data_version


if __name__ == '__main__':
    if len(sys.argv) >= 2:
        port = int(sys.argv[1])
    else:
        port = None
    rhevm = FakeRhevm4(port=port)
    rhevm.run()
