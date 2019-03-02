from __future__ import print_function

import tempfile
import os
import shutil

from virtwhotest import TestBase, VirtBackendTestMixin

from fake_nutanix import FakeNutanix


class Rhevm4Test(TestBase, VirtBackendTestMixin):
    virt = 'nutanix'
    hypervisorType = 'qemu'

    @classmethod
    def setUpClass(cls):
        TestBase.setUpClass()
        cls.server = FakeNutanix()
        cls.server.start()
        cls.config_dir = tempfile.mkdtemp()
        with open(os.path.join(cls.config_dir, "test.conf"), "w") as f:
            f.write(("""
[test]
type=nutanix
server=https://localhost:%s/
username=%s
password=%s
owner=owner
env=env
""") % (cls.server.port, cls.server.username, cls.server.password))
        cls.arguments = [
            '-c=%s' % os.path.join(cls.config_dir, "test.conf")
        ]

    @classmethod
    def tearDownClass(cls):
        TestBase.tearDownClass()
        cls.server.terminate()
        cls.server.join()
        shutil.rmtree(cls.config_dir)
