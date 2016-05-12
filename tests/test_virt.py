
import os
import tempfile
import shutil

from base import TestBase

from virtwho.config import ConfigManager
from virtwho.virt import HostGuestAssociationReport, Hypervisor, Guest


xvirt = type("", (), {'CONFIG_TYPE': 'xxx'})()


class TestVirtInclude(TestBase):
    def test_filter_hosts(self):
        self.filter_hosts('filter_hosts=12345')

    def test_exclude_hosts(self):
        self.filter_hosts('exclude_hosts=00000')

    def test_filter_host_uuids(self):
        self.filter_hosts('filter_host_uuids=12345')

    def test_exclude_host_uuids(self):
        self.filter_hosts('exclude_host_uuids=00000')

    def filter_hosts(self, config):
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=esx
server=does.not.exist
username=username
password=password
owner=owner
env=env
{config}
""".format(config=config))
        config_manager = ConfigManager(self.logger, config_dir)
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0]

        included_hypervisor = Hypervisor('12345', guestIds=[
            Guest('guest-2', xvirt, Guest.STATE_RUNNING),
        ])
        excluded_hypervisor = Hypervisor('00000', guestIds=[
            Guest('guest-1', xvirt, Guest.STATE_RUNNING),
        ])

        assoc = {
            'hypervisors': [
                excluded_hypervisor,
                included_hypervisor,
            ]
        }

        report = HostGuestAssociationReport(config, assoc)
        assert report.association == {
            'hypervisors': [
                included_hypervisor
            ]
        }
