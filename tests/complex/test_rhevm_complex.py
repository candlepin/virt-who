from __future__ import print_function

from virtwho.datastore import Datastore
from virtwho.virt import Virt
from virtwho.virt.rhevm.rhevm import RhevmConfigSection
from virtwhotest import TestBase, VirtBackendTestMixin

from fake_rhevm import FakeRhevm


class RhevmTest(TestBase, VirtBackendTestMixin):
    virt = 'rhevm'
    hypervisorType = 'qemu'

    @staticmethod
    def create_config(name, wrapper, **kwargs):
        config = RhevmConfigSection(name, wrapper)
        config.update(**kwargs)
        config.validate()
        return config

    @classmethod
    def setUpClass(cls):
        TestBase.setUpClass()
        cls.server = FakeRhevm()
        cls.create_config(name='test', wrapper=None, type='rhevm', server='http://localhost:%s/' % cls.server.port,
               username=cls.server.username, password=cls.server.password, owner='owner', env='env')
        cls.arguments = []
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        TestBase.tearDownClass()
        cls.server.terminate()
        cls.server.join()
