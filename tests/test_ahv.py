from __future__ import print_function

import six

from base import TestBase
from mock import patch, call, ANY, MagicMock
from requests import Session
from six.moves.queue import Queue
from threading import Event

from virtwho import DefaultInterval
from virtwho import virt
from virtwho.datastore import Datastore
from virtwho.virt.ahv.ahv import AhvConfigSection
from virtwho.virt import Virt, VirtError, Guest, Hypervisor



MY_SECTION_NAME = 'test-ahv'
DefaultUpdateInterval = 1800
# Values used for testing AhvConfigSection.
PE_SECTION_VALUES = {
    'type': 'ahv',
    'server': '10.10.10.10',
    'username': 'root',
    'password': 'root_password',
    'owner': 'nutanix',
    'hypervisor_id': 'uuid',
    'is_hypervisor': True,
    'ahv_internal_debug': False,
    'update_interval': 60,
    'wait_time_in_sec': 900
}

HOST_UVM_MAP = \
 {u'08469de5-be42-43e6-8c32-20167d3b58f7':
           {u'oplog_disk_pct': 3.4,
            u'memory_capacity_in_bytes': 135009402880,
            u'has_csr': False,
            u'default_vm_storage_container_uuid': None,
            u'hypervisor_username': u'root',
            u'key_management_device_to_certificate_status': {},
            u'service_vmnat_ip': None,
            u'hypervisor_key': u'10.53.97.188',
            u'acropolis_connection_state': u'kConnected',
            u'management_server_name': u'10.53.97.188',
            u'failover_cluster_fqdn': None,
            u'serial': u'OM155S016008',
            u'bmc_version': u'01.92',
            u'hba_firmwares_list':
             [{u'hba_model': u'LSI Logic SAS3008',
               u'hba_version': u'MPTFW-06.00.00.00-IT'}],
            u'hypervisor_state': u'kAcropolisNormal',
            u'num_cpu_threads': 32,
            u'monitored': True,
            u'uuid': u'08469de5-be42-43e6-8c32-20167d3b58f7',
            u'reboot_pending': False,
            u'cpu_capacity_in_hz': 38384000000,
            u'num_cpu_sockets': 2,
            u'host_maintenance_mode_reason': None,
            u'hypervisor_address': u'10.53.97.188',
            u'host_gpus': None,
            u'failover_cluster_node_state': None,
            u'state': u'NORMAL',
            u'num_cpu_cores': 16,
            'guest_list':
             [{u'vm_features':
                {u'AGENT_VM': False,
                 u'VGA_CONSOLE': True},
               u'name': u'am2', u'num_cores_per_vcpu': 1,
               u'gpus_assigned': False, u'num_vcpus': 2,
               u'memory_mb': 4096,
               u'power_state': u'on',
               u'ha_priority': 0,
               u'allow_live_migrate': True,
               u'timezone': u'America/Los_Angeles',
               u'vm_logical_timestamp': 48,
               u'host_uuid': u'08469de5-be42-43e6-8c32-20167d3b58f7',
               u'uuid': u'01dcfc0b-3092-4f1b-94fb-81b44ed352be'},
              {u'vm_features':
                {u'AGENT_VM': False, u'VGA_CONSOLE': True},
               u'name': u'am3',
               u'num_cores_per_vcpu': 1,
               u'gpus_assigned': False,
               u'num_vcpus': 2, u'memory_mb': 4096,
               u'power_state': u'on',
               u'ha_priority': 0,
               u'allow_live_migrate': True,
               u'timezone': u'America/Los_Angeles',
               u'vm_logical_timestamp': 3,
               u'host_uuid': u'08469de5-be42-43e6-8c32-20167d3b58f7',
               u'uuid': u'422f9171-db1f-48b0-a3de-b0bb92a8f559'},
              {u'vm_features':
                {u'AGENT_VM': False,
                 u'VGA_CONSOLE': True},
               u'name': u'win_vm',
               u'num_cores_per_vcpu': 1,
               u'gpus_assigned': False,
               u'num_vcpus': 2,
               u'memory_mb': 4096,
               u'power_state': u'on',
               u'ha_priority': 0,
               u'allow_live_migrate': True,
               u'timezone': u'America/Los_Angeles',
               u'vm_logical_timestamp': 3,
               u'host_uuid': u'08469de5-be42-43e6-8c32-20167d3b58f7',
               u'uuid': u'98839f35-bd62-4255-a7cd-7668bc143554'}],
            u'cpu_model': u'Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz',
            u'ipmi_username': u'ADMIN',
            u'service_vmid': u'0005809e-62e4-75c7-611b-0cc47ac3b354::7',
            u'bmc_model': u'X10_ATEN',
            u'host_nic_ids': [],
            u'cluster_uuid': u'0005809e-62e4-75c7-611b-0cc47ac3b354',
            u'ipmi_password': None,
            u'cpu_frequency_in_hz': 2399000000,
            u'stats':
             {u'num_read_io': u'8',
              u'controller_read_io_bandwidth_kBps': u'0',
              u'content_cache_hit_ppm': u'1000000',
              },
            u'num_vms': 4, u'default_vm_storage_container_id': None,
            u'metadata_store_status': u'kNormalMode',
            u'name': u'foyt-4', u'hypervisor_password': None,
            u'service_vmnat_port': None,
            u'hypervisor_full_name': u'Nutanix 20180802.100874',
            u'is_degraded': False, u'host_type': u'HYPER_CONVERGED',
            u'default_vhd_storage_container_uuid': None,
            u'block_serial': u'15SM60250038',
            u'disk_hardware_configs':
             {u'1':
               {
                u'mount_path': u'/home/nutanix/data/stargate-storage/disks/BTHC506101XL480MGN',
                },
              u'3':
               {
                u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG8E6QE',
                },
              u'2':
               {
                u'mount_path': u'/home/nutanix/data/stargate-storage/disks/BTHC50610246480MGN',
                },
              u'5':
               {
                u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG8E835',
                },
              u'4': {
                     u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG8E8B1',
                     },
              u'6': {
                     u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG8E7B3',
                     }},
            u'ipmi_address': u'10.49.27.28', u'bios_model': u'0824',
            u'default_vm_location': None, u'hypervisor_type': u'kKvm',
            u'service_vmexternal_ip': u'10.53.97.192',
            u'controller_vm_backplane_ip': u'10.53.97.192'},
 u'54830446-b55e-4f16-aa74-7b6a9ac9a7a4':
  {u'oplog_disk_pct': 3.4,
            u'memory_capacity_in_bytes': 135009402880, u'has_csr': False,
            u'default_vm_storage_container_uuid': None,
            u'hypervisor_username': u'root',
            u'service_vmnat_ip': None, u'hypervisor_key': u'10.53.97.187',
            u'acropolis_connection_state': u'kConnected',
            u'hypervisor_state': u'kAcropolisNormal',
            u'num_cpu_threads': 32, u'monitored': True,
            u'uuid': u'54830446-b55e-4f16-aa74-7b6a9ac9a7a4',
            u'reboot_pending': False, u'cpu_capacity_in_hz': 38384000000,
            u'num_cpu_sockets': 2, u'host_maintenance_mode_reason': None,
            u'hypervisor_address': u'10.53.97.187', u'host_gpus': None,
            u'failover_cluster_node_state': None, u'state': u'NORMAL',
            u'num_cpu_cores': 16, u'block_model': u'UseLayout',
            'guest_list':
             [{u'vm_features':
                {u'AGENT_VM': False, u'VGA_CONSOLE': True},
               u'name': u'PC', u'num_cores_per_vcpu': 1,
               u'gpus_assigned': False, u'num_vcpus': 4,
               u'memory_mb': 16384, u'power_state': u'on',
               u'ha_priority': 0, u'allow_live_migrate': True,
               u'timezone': u'UTC', u'vm_logical_timestamp': 10,
               u'host_uuid': u'54830446-b55e-4f16-aa74-7b6a9ac9a7a4',
               u'uuid': u'd90b5443-97f0-47eb-986d-f14e062448d4'},
              {u'vm_features':
                {u'AGENT_VM': False, u'VGA_CONSOLE': True},
               u'name': u'am1', u'num_cores_per_vcpu': 1,
               u'gpus_assigned': False, u'num_vcpus': 2,
               u'memory_mb': 4096, u'power_state': u'on',
               u'ha_priority': 0, u'allow_live_migrate': True,
               u'timezone': u'America/Los_Angeles',
               u'vm_logical_timestamp': 14,
               u'host_uuid': u'54830446-b55e-4f16-aa74-7b6a9ac9a7a4',
               u'uuid': u'0af0a010-0ad0-4fba-aa33-7cc3d0b6cb7e'}],
            u'cpu_model': u'Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz',
            u'ipmi_username': u'ADMIN',
            u'service_vmid': u'0005809e-62e4-75c7-611b-0cc47ac3b354::6',
            u'bmc_model': u'X10_ATEN', u'host_nic_ids': [],
            u'cluster_uuid': u'0005809e-62e4-75c7-611b-0cc47ac3b354',
            u'stats':
             {u'num_read_io': u'27',
              u'controller_read_io_bandwidth_kBps': u'0',
              u'content_cache_hit_ppm': u'1000000',
             }, u'backplane_ip': None,
            u'vzone_name': u'', u'default_vhd_location': None,
            u'metadata_store_status_message': u'Metadata store enabled on the node',
            u'num_vms': 3, u'default_vm_storage_container_id': None,
            u'metadata_store_status': u'kNormalMode', u'name': u'foyt-3',
            u'hypervisor_password': None, u'service_vmnat_port': None,
            u'hypervisor_full_name': u'Nutanix 20180802.100874',
            u'is_degraded': False, u'host_type': u'HYPER_CONVERGED',
            u'default_vhd_storage_container_uuid': None,
            u'block_serial': u'15SM60250038',
            u'disk_hardware_configs':
             {u'1':
               {
                u'mount_path': u'/home/nutanix/data/stargate-storage/disks/BTHC506101ST480MGN',
                },
              u'3':
               {
                u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG8DXYY',
                },
              u'2': {
                     u'mount_path': u'/home/nutanix/data/stargate-storage/disks/BTHC506101D4480MGN',
                     },
              u'5': {
                     u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG8DQRM',
                     },
              u'4': {
                     u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG8DJ7E',
                     },
              u'6': {
                     u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG8DVGG',
                     }},
            u'ipmi_address': u'10.49.27.27', u'bios_model': u'0824',
            u'hypervisor_type': u'kKvm',
            u'service_vmexternal_ip': u'10.53.97.191',
            u'controller_vm_backplane_ip': u'10.53.97.191'
 },
 u'acc819fe-e0ff-4963-93a4-5a0e1d3c77d3':
           {u'oplog_disk_pct': 3.4,
            u'memory_capacity_in_bytes': 270302969856, u'has_csr': False,
            u'default_vm_storage_container_uuid': None,
            u'hypervisor_username': u'root',
            u'key_management_device_to_certificate_status': {},
            u'service_vmnat_ip': None, u'hypervisor_key': u'10.53.96.75',
            u'acropolis_connection_state': u'kConnected',
            u'management_server_name': u'10.53.96.75',
            u'failover_cluster_fqdn': None, u'serial': u'ZM162S002621',
            u'bmc_version': u'01.97',
            u'hba_firmwares_list':
             [{u'hba_model': u'LSI Logic SAS3008',
               u'hba_version': u'MPTFW-10.00.03.00-IT'}],
            u'hypervisor_state': u'kAcropolisNormal',
            u'num_cpu_threads': 32, u'monitored': True,
            u'uuid': u'acc819fe-e0ff-4963-93a4-5a0e1d3c77d3',
            u'num_cpu_sockets': 2, u'host_maintenance_mode_reason': None,
            u'hypervisor_address': u'10.53.96.75',
            'guest_list':
             [{u'vm_features': {u'AGENT_VM': False, u'VGA_CONSOLE': True},
               u'name': u'am_RH_satellite', u'num_cores_per_vcpu': 2,
               u'gpus_assigned': False, u'num_vcpus': 4, u'memory_mb': 16384,
               u'power_state': u'on', u'ha_priority': 0,
               u'allow_live_migrate': True, u'timezone': u'America/Los_Angeles',
               u'vm_logical_timestamp': 5,
               u'host_uuid': u'acc819fe-e0ff-4963-93a4-5a0e1d3c77d3',
               u'uuid': u'e30f381d-d4bc-4958-a88c-79448efe5112'},
              {u'vm_features': {u'AGENT_VM': False, u'VGA_CONSOLE': True},
               u'name': u'am4', u'num_cores_per_vcpu': 1,
               u'gpus_assigned': False, u'num_vcpus': 2, u'memory_mb': 4096,
               u'power_state': u'on', u'ha_priority': 0,
               u'allow_live_migrate': True, u'timezone': u'America/Los_Angeles',
               u'vm_logical_timestamp': 2,
               u'host_uuid': u'acc819fe-e0ff-4963-93a4-5a0e1d3c77d3',
               u'uuid': u'f1e3362b-0377-4d70-bccd-63d2a1c09225'}],
            u'dynamic_ring_changing_node': None,
            u'cpu_model': u'Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz',
            u'ipmi_username': u'ADMIN',
            u'cluster_uuid': u'0005809e-62e4-75c7-611b-0cc47ac3b354',
            u'ipmi_password': None, u'cpu_frequency_in_hz': 2400000000,
            u'stats': {u'num_read_io': u'47',
                       u'controller_read_io_bandwidth_kBps': u'0',
                       u'content_cache_hit_ppm': u'1000000',
                       }, u'backplane_ip': None,
            u'num_vms': 3,
            u'name': u'watermelon02-4', u'hypervisor_password': None,
            u'hypervisor_full_name': u'Nutanix 20180802.100874',
            u'is_degraded': False, u'host_type': u'HYPER_CONVERGED',
            u'default_vhd_storage_container_uuid': None,
            u'block_serial': u'16AP60170033', u'usage_stats': {
            },
            u'disk_hardware_configs': {
             u'1': {
                    u'mount_path': u'/home/nutanix/data/stargate-storage/disks/BTHC549209M3480MGN',
                    },
             u'3': {
                    u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG9TRZQ'},
             u'2': {
                    u'mount_path': u'/home/nutanix/data/stargate-storage/disks/BTHC550503XF480MGN',
                    },
             u'5': {
                    u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG9TS0N',
                    },
             u'4': {
                    u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG9TSF7',
                    },
             u'6': {
                    u'mount_path': u'/home/nutanix/data/stargate-storage/disks/9XG9TREW',
                    }}, u'ipmi_address': u'10.49.26.188',
            u'bios_model': u'0824', u'default_vm_location': None,
            u'hypervisor_type': u'kKvm',
            u'position': {u'ordinal': 4, u'physical_position': None,
                          u'name': u''},
            u'service_vmexternal_ip': u'10.53.96.79',
            u'controller_vm_backplane_ip': u'10.53.96.79'}}


class TestAhvConfigSection(TestBase):
    """
    Test base for testing class AhvConfigSection.
    """

    def __init__(self, *args, **kwargs):
        super(TestAhvConfigSection, self).__init__(*args, **kwargs)
        self.ahv_config = None

    def init_virt_config_section(self, is_pc=False):
        """
        Method executed before each unit test.
        """
        self.ahv_config = AhvConfigSection(MY_SECTION_NAME, None)
        if is_pc:
            self.ahv_config['prism_central'] = True
        # We need to set values using this way, because we need
        # to trigger __setitem__ of virt_config.
        for key, value in PE_SECTION_VALUES.items():
            self.ahv_config[key] = value

    def test_validate_ahv_PE_config(self):
        """
        Test validation of ahv section.
        """
        # PE validation.
        self.init_virt_config_section()
        result = self.ahv_config.validate()
        self.assertEqual(len(result), 0)

        # PC validation.
        self.init_virt_config_section(is_pc=True)
        result = self.ahv_config.validate()
        self.assertEqual(len(result), 0)

    def test_validate_ahv_invalid_server_ip(self):
        """
        Test validation of ahv config. Invalid server IP.
        """
        self.init_virt_config_section()
        self.ahv_config['server'] = '10.0.0.'
        result = self.ahv_config.validate()
        expected_result = ['Invalid server IP address provided']
        six.assertCountEqual(self, expected_result, result)

    def test_validate_ahv_non_latin_username(self):
        """
        Test validation of ahv config. Invalid server IP.
        """
        self.init_virt_config_section()
        self.ahv_config['username'] = 'příšerně žluťoučký kůň'
        result = self.ahv_config.validate()
        self.assertEqual(len(result), 0)

    def test_validate_ahv_non_latin_password(self):
        """
        Test validation of ahv config. Invalid server IP.
        """
        self.init_virt_config_section()
        self.ahv_config['password'] = 'pěl úděsné ódy'
        result = self.ahv_config.validate()
        self.assertEqual(len(result), 0)

    def test_validate_ahv_config_missing_username_password(self):
        """
        Test validation of ahv config. Username and password is required.
        """
        self.init_virt_config_section()
        del self.ahv_config['username']
        del self.ahv_config['password']
        result = self.ahv_config.validate()
        expected_result = [
            ('error', 'Required option: "username" not set.'),
            ('error', 'Required option: "password" not set.')
        ]
        six.assertCountEqual(self, expected_result, result)

    def test_validate_ahv_config_invalid_internal_debug_flag(self):
        """
        Test validation of ahv config. If update_interval and internal debug
        are not set then we get a warning message for each flag.
        """
        self.init_virt_config_section()
        self.ahv_config['update_interval'] = 40
        result = self.ahv_config.validate()
        message = "Interval value can't be lower than {min} seconds. " \
                  "Default value of {min} " \
                  "seconds will be used.".format(min=DefaultUpdateInterval)
        expected_result = [("warning", message)]
        six.assertCountEqual(self, expected_result, result)


class TestAhv(TestBase):

    @staticmethod
    def create_config(name, wrapper, **kwargs):
        config = AhvConfigSection(name, wrapper)
        config.update(**kwargs)
        config.validate()
        return config

    def setUp(self, is_pc=False, config=None):
        if config is None:
            config = self.create_config(
                name='test',
                wrapper=None,
                type='ahv',
                server='10.10.10.10',
                username='username',
                password='password',
                owner='owner',
                prism_central=is_pc
            )
        self.ahv = Virt.from_config(self.logger, config, Datastore(),
                                    interval=DefaultInterval)

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface._progressbar')
    def run_once(self, queue=None):
        """Run AHV in oneshot mode."""
        self.ahv._oneshot = True
        self.ahv.dest = queue or Queue()
        self.ahv._terminate_event = Event()
        self.ahv._oneshot = True
        self.ahv._interval = 0
        self.ahv._run()

    @patch.object(Session, 'get')
    def test_connect_PE(self, mock_get):
        mock_get.return_value.status_code = 200
        self.run_once()

        self.assertEqual(mock_get.call_count, 3)
        call_list = [
            call('https://10.10.10.10:9440/api/nutanix/v2.0/clusters',
                 data=ANY, headers=ANY, timeout=ANY, verify=ANY),
            call('https://10.10.10.10:9440/api/nutanix/v2.0/vms',
                 data=ANY, headers=ANY, timeout=ANY, verify=ANY),
            call('https://10.10.10.10:9440/api/nutanix/v2.0/hosts',
                 data=ANY, headers=ANY, timeout=ANY, verify=ANY)
        ]
        mock_get.assert_has_calls(call_list, any_order=True)

    @patch.object(Session, 'post')
    def test_connect_PC(self, mock_post):
        self.setUp(is_pc=True)

        mock_post.return_value.status_code = 200
        self.run_once()

        self.assertEqual(mock_post.call_count, 3)
        call_list = [
            call('https://10.10.10.10:9440/api/nutanix/v3/clusters/list',
                 data=ANY, headers=ANY, timeout=ANY, verify=ANY),
            call('https://10.10.10.10:9440/api/nutanix/v3/vms/list',
                 data=ANY, headers=ANY, timeout=ANY, verify=ANY),
            call('https://10.10.10.10:9440/api/nutanix/v3/hosts/list',
                 data=ANY, headers=ANY, timeout=ANY, verify=ANY)
        ]
        mock_post.assert_has_calls(call_list, any_order=True)

    @patch.object(Session, 'get')
    def test_invalid_login_PE(self, mock_get):
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 401
        self.assertRaises(VirtError, self.run_once)

        mock_get.return_value.status_code = 403
        self.assertRaises(VirtError, self.run_once)

    def test_non_latin1_username_and_password(self):
        """
        When non-latin1 string is used as username or password, then it has
        to be converted to bytes in AHV interface.
        """
        config = self.create_config(
            name='test',
            wrapper=None,
            type='ahv',
            server='10.10.10.10',
            username='žluťoučký kůň',
            password='pěl úděsné ódy',
            owner='owner',
            prism_central=True
        )
        self.setUp(is_pc=True, config=config)
        # Test that non latin1 username and password were converted to bytes
        assert self.ahv._interface._user == b'\xc5\xbelu\xc5\xa5ou\xc4\x8dk\xc3\xbd k\xc5\xaf\xc5\x88'
        assert self.ahv._interface._password == b'p\xc4\x9bl \xc3\xbad\xc4\x9bsn\xc3\xa9 \xc3\xb3dy'

    @patch.object(Session, 'post')
    def test_invalid_login_PC(self, mock_post):
        self.setUp(is_pc=True)
        mock_post.return_value.ok = False
        mock_post.return_value.status_code = 401
        self.assertRaises(VirtError, self.run_once)

        mock_post.return_value.status_code = 403
        self.assertRaises(VirtError, self.run_once)

    @patch.object(Session, 'get')
    def test_connection_conflict_PE(self, mock_get):
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 409
        self.assertRaises(VirtError, self.run_once)

    @patch.object(Session, 'post')
    def test_connection_conflict_PC(self, mock_post):
        self.setUp(is_pc=True)
        mock_post.return_value.ok = False
        mock_post.return_value.status_code = 409
        self.assertRaises(VirtError, self.run_once)

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface.get_vm', return_value=None)
    @patch.object(Session, 'get')
    def test_no_retry_http_erros_PE(self, mock_get, mock_get_vm):
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 400
        mock_get.return_value.text = 'Bad Request'
        self.assertEqual(mock_get_vm.return_value, None)

        mock_get.return_value.status_code = 404
        mock_get.return_value.text = 'Not Found Error'
        self.assertEqual(mock_get_vm.return_value, None)

        mock_get.return_value.status_code = 500
        mock_get.return_value.text = 'Internal Server Error'
        self.assertEqual(mock_get_vm.return_value, None)

        mock_get.return_value.status_code = 502
        mock_get.return_value.tex = 'Bad Gateway'
        self.assertEqual(mock_get_vm.return_value, None)

        mock_get.return_value.status_code = 503
        mock_get.return_value.text = 'Service Unavailable '
        self.assertEqual(mock_get_vm.return_value, None)

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface.get_vm', return_value=None)
    @patch.object(Session, 'post')
    def test_no_retry_http_erros_PC(self, mock_post, mock_get_vm):
        self.setUp(is_pc=True)
        mock_post.return_value.ok = False
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = 'Bad Request'
        self.assertEqual(mock_get_vm.return_value, None)

        mock_post.return_value.status_code = 404
        mock_post.return_value.text = 'Not Found Error'
        self.assertEqual(mock_get_vm.return_value, None)

        mock_post.return_value.status_code = 500
        mock_post.return_value.text = 'Internal Server Error'
        self.assertEqual(mock_get_vm.return_value, None)

        mock_post.return_value.status_code = 502
        mock_post.return_value.tex = 'Bad Gateway'
        self.assertEqual(mock_get_vm.return_value, None)

        mock_post.return_value.status_code = 503
        mock_post.return_value.text = 'Service Unavailable '
        self.assertEqual(mock_get_vm.return_value, None)

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface.build_host_to_uvm_map')
    def test_getHostGuestMapping(self, host_to_uvm_map):
        host_to_uvm_map.return_value = HOST_UVM_MAP

        expected_result = []

        for host_uuid in HOST_UVM_MAP:
           host = HOST_UVM_MAP[host_uuid]
           hypervisor_id = host_uuid
           host_name = host['name']
           cluster_uuid = host['cluster_uuid']
           guests = []
           for guest_vm in host['guest_list']:
               state = virt.Guest.STATE_RUNNING
               guests.append(Guest(guest_vm['uuid'], self.ahv.CONFIG_TYPE,
                                   state))

           facts = {
            Hypervisor.CPU_SOCKET_FACT: '2',
            Hypervisor.HYPERVISOR_TYPE_FACT: u'kKvm',
            Hypervisor.HYPERVISOR_VERSION_FACT: 'Nutanix 20180802.100874',
            Hypervisor.HYPERVISOR_CLUSTER: str(cluster_uuid),
            Hypervisor.SYSTEM_UUID_FACT: str(host_uuid)
           }

           expected_result.append(Hypervisor(
            name=host_name,
            hypervisorId=hypervisor_id,
            guestIds=guests,
            facts=facts
           ))

        result = self.ahv.getHostGuestMapping()['hypervisors']

        self.assertEqual(len(result), len(expected_result), 'lists length '
                                                            'do not match')
        for index in range(0, len(result)):
          self.assertEqual(expected_result[index].toDict(),
                           result[index].toDict())

