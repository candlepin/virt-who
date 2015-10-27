
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
        cls.arguments = [
            '--esx',
            '--esx-server=http://localhost:%s' % cls.server.port,
            '--esx-username=%s' % cls.server.username,
            '--esx-password=%s' % cls.server.password,
            '--esx-owner=owner',
            '--esx-env=env'
        ]

    @classmethod
    def tearDownClass(cls):
        TestBase.tearDownClass()
        cls.server.terminate()
        cls.server.join()
