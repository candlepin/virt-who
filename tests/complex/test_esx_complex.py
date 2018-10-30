from __future__ import print_function

import os
import tempfile

import shutil

from virtwho import log
from virtwhotest import TestBase, VirtBackendTestMixin

from fake_esx import FakeEsx


class EsxTest(TestBase, VirtBackendTestMixin):
    virt = 'esx'
    hypervisorType = 'vmware'

    @classmethod
    def setUpClass(cls):
        TestBase.setUpClass()
        cls.server = FakeEsx()
        cls.server.start()
        cls.config_dir = tempfile.mkdtemp()
#        cls.addCleanup(shutil.rmtree, cls.config_dir)
        print("server=http://localhost:%s, username=%s, password=%s" % (cls.server.port, cls.server.username, cls.server.password))
        with open(os.path.join(cls.config_dir, "test.conf"), "w") as f:
            f.write(("""
[test]
type=esx
server=http://localhost:%s
username=%s
password=%s
owner=owner
env=env
""") % (cls.server.port, cls.server.username, cls.server.password))

        cls.arguments = [
            '--c=%s' % os.path.join(cls.config_dir, "test.conf")
        ]

    @classmethod
    def tearDownClass(cls):
        TestBase.tearDownClass()
        cls.server.terminate()
        cls.server.join()
