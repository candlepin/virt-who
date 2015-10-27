
from virtwhotest import TestBase, VirtBackendTestMixin

from fake_rhevm import FakeRhevm


class RhevmTest(TestBase, VirtBackendTestMixin):
    virt = 'rhevm'
    hypervisorType = 'qemu'

    @classmethod
    def setUpClass(cls):
        TestBase.setUpClass()
        cls.server = FakeRhevm()
        cls.server.start()
        cls.arguments = [
            '--rhevm',
            '--rhevm-server=http://localhost:%s/' % cls.server.port,
            '--rhevm-username=%s' % cls.server.username,
            '--rhevm-password=%s' % cls.server.password,
            '--rhevm-owner=owner',
            '--rhevm-env=env'
        ]

    @classmethod
    def tearDownClass(cls):
        TestBase.tearDownClass()
        cls.server.terminate()
        cls.server.join()
