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

import tempfile
import os
import shutil

import virtwhotest

from fake_rhevm4 import FakeRhevm4


class Rhevm4Test(virtwhotest.TestBase):
    virt = 'rhevm'
    hypervisorType = 'qemu'

    @classmethod
    def setUpClass(cls):
        super(Rhevm4Test, cls).setUpClass()
        cls.server = FakeRhevm4()
        cls.server.start()
        cls.config_dir = tempfile.mkdtemp()
        with open(os.path.join(cls.config_dir, "test.conf"), "w") as f:
            config_file_content = """
[test]
type=rhevm
server=http://localhost:%s/
username=%s
password=%s
owner=owner

rhsm_hostname=localhost
rhsm_port=%s
rhsm_username=admin
rhsm_password=admin
rhsm_org=admin
rhsm_prefix=/
rhsm_insecure=1
""" % (cls.server.port, cls.server.username, cls.server.password, cls.sam.port)
            print("Using config: %s" % config_file_content)
            f.write(config_file_content)
        cls.arguments = [
            '-c=%s' % os.path.join(cls.config_dir, "test.conf")
        ]

    @classmethod
    def tearDownClass(cls):
        super(Rhevm4Test, cls).tearDownClass()
        cls.server.terminate()
        cls.server.join()
        shutil.rmtree(cls.config_dir)
