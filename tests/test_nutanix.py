# -*- coding: utf-8 -*-
# pylint: disable=C0103,C0301,C0413,missing-docstring,W0212

from __future__ import print_function
"""
Test of Nutanix virtualization backend.

Copyright (C) 2016 Joshua Preston <mrjoshuap@redhat.com>

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

import os
from threading import Event
import requests
from mock import patch, call, ANY, MagicMock
from six.moves.queue import Queue

from base import TestBase
from proxy import Proxy

from virtwho.virt import Virt, VirtError, Guest, Hypervisor
from virtwho.virt.nutanix.nutanix import NutanixConfigSection
from virtwho.datastore import Datastore


uuids = {
    'cluster': '00000000-0000-0000-0000-000000000001',
    'host': '00000000-0000-0000-0000-000000000002',
    'vm': '00000000-0000-0000-0000-000000000003',
}


CLUSTERS_JSON = '''{{
  "metadata": {{
    "grand_total_entities": 1,
    "total_entities": 1,
    "filter_criteria": "",
    "sort_criteria": "",
    "page": 1,
    "count": 1,
    "start_index": 1,
    "end_index": 1
  }},
  "entities": [
    {{
      "id": "{cluster}::2247383588839889017",
      "uuid": "{cluster}",
      "cluster_incarnation_id": 5725941660045689159,
      "cluster_uuid": "{cluster}",
      "name": "Cetus",
      "cluster_external_ipaddress": "172.30.0.2",
      "cluster_external_data_services_ipaddress": null,
      "cluster_masquerading_ipaddress": null,
      "cluster_masquerading_port": null,
      "timezone": "UTC",
      "support_verbosity_type": "BASIC_COREDUMP",
      "operation_mode": "Normal",
      "encrypted": true,
      "storage_type": "all_flash",
      "cluster_functions": [
        "NDFS"
      ],
      "is_lts": true,
      "num_nodes": 1,
      "block_serials": [
        "null"
      ],
      "version": "5.10",
      "full_version": "el7.3-release-euphrates-5.10-stable-973448674a02496aef1d1486e76c673a4447e459",
      "target_version": "5.10",
      "external_subnet": "172.0.0.0/255.0.0.0",
      "internal_subnet": "172.0.0.0/255.0.0.0",
      "ncc_version": "ncc-3.6.3",
      "enable_lock_down": false,
      "enable_password_remote_login_to_cluster": true,
      "fingerprint_content_cache_percentage": 100,
      "ssd_pinning_percentage_limit": 25,
      "enable_shadow_clones": true,
      "global_nfs_white_list": [],
      "name_servers": [
        "169.254.169.254",
        "8.8.8.8"
      ],
      "ntp_servers": [],
      "service_centers": [],
      "http_proxies": [],
      "rackable_units": [
        {{
          "id": 8,
          "rackable_unit_uuid": "44db4ec6-da0c-4cc2-acfd-69bf28026770",
          "model": "Null",
          "model_name": "null",
          "location": null,
          "serial": "null",
          "positions": [
            "1"
          ],
          "nodes": [
            2
          ],
          "node_uuids": [
            "0bb9eaec-1947-472b-aa05-cb9ea89230eb"
          ]
        }}
      ],
      "public_keys": [],
      "smtp_server": null,
      "hypervisor_types": [
        "kKvm"
      ],
      "cluster_redundancy_state": {{
        "current_redundancy_factor": 1,
        "desired_redundancy_factor": 1,
        "redundancy_status": {{
          "kCassandraPrepareDone": true,
          "kZookeeperPrepareDone": true
        }}
      }},
      "multicluster": false,
      "cloudcluster": false,
      "has_self_encrypting_drive": false,
      "is_upgrade_in_progress": false,
      "security_compliance_config": {{
        "schedule": "DAILY",
        "enable_aide": false,
        "enable_core": false,
        "enable_high_strength_password": false,
        "enable_banner": false,
        "enable_snmpv3_only": false
      }},
      "hypervisor_security_compliance_config": {{
        "schedule": "DAILY",
        "enable_aide": false,
        "enable_core": false,
        "enable_high_strength_password": false,
        "enable_banner": false
      }},
      "hypervisor_lldp_config": {{
        "enable_lldp_tx": true
      }},
      "cluster_arch": "X86_64",
      "iscsi_config": null,
      "domain": null,
      "nos_cluster_and_hosts_domain_joined": false,
      "all_hyperv_nodes_in_failover_cluster": false,
      "credential": null,
      "stats": {{
        "hypervisor_avg_io_latency_usecs": "0",
        "num_read_iops": "0",
        "hypervisor_write_io_bandwidth_kBps": "0",
        "timespan_usecs": "30000000",
        "controller_num_read_iops": "0",
        "read_io_ppm": "500000",
        "controller_num_iops": "0",
        "total_read_io_time_usecs": "-1",
        "controller_total_read_io_time_usecs": "0",
        "replication_transmitted_bandwidth_kBps": "0",
        "hypervisor_num_io": "0",
        "controller_total_transformed_usage_bytes": "-1",
        "hypervisor_cpu_usage_ppm": "20685",
        "controller_num_write_io": "0",
        "avg_read_io_latency_usecs": "-1",
        "content_cache_logical_ssd_usage_bytes": "0",
        "controller_total_io_time_usecs": "0",
        "controller_total_read_io_size_kbytes": "0",
        "controller_num_seq_io": "-1",
        "controller_read_io_ppm": "0",
        "content_cache_num_lookups": "0",
        "controller_total_io_size_kbytes": "0",
        "content_cache_hit_ppm": "0",
        "controller_num_io": "0",
        "hypervisor_avg_read_io_latency_usecs": "0",
        "content_cache_num_dedup_ref_count_pph": "100",
        "num_write_iops": "0",
        "controller_num_random_io": "-1",
        "num_iops": "0",
        "replication_received_bandwidth_kBps": "0",
        "hypervisor_num_read_io": "0",
        "hypervisor_total_read_io_time_usecs": "0",
        "controller_avg_io_latency_usecs": "0",
        "hypervisor_hyperv_cpu_usage_ppm": "-1",
        "num_io": "4",
        "controller_num_read_io": "0",
        "hypervisor_num_write_io": "0",
        "controller_seq_io_ppm": "-1",
        "controller_read_io_bandwidth_kBps": "0",
        "controller_io_bandwidth_kBps": "0",
        "hypervisor_hyperv_memory_usage_ppm": "-1",
        "hypervisor_timespan_usecs": "29847775",
        "hypervisor_num_write_iops": "0",
        "replication_num_transmitted_bytes": "0",
        "total_read_io_size_kbytes": "16",
        "hypervisor_total_io_size_kbytes": "0",
        "avg_io_latency_usecs": "320",
        "hypervisor_num_read_iops": "0",
        "content_cache_saved_ssd_usage_bytes": "0",
        "controller_write_io_bandwidth_kBps": "0",
        "controller_write_io_ppm": "0",
        "hypervisor_avg_write_io_latency_usecs": "0",
        "hypervisor_total_read_io_size_kbytes": "0",
        "read_io_bandwidth_kBps": "0",
        "hypervisor_esx_memory_usage_ppm": "-1",
        "hypervisor_memory_usage_ppm": "278573",
        "hypervisor_num_iops": "0",
        "hypervisor_io_bandwidth_kBps": "0",
        "controller_num_write_iops": "0",
        "total_io_time_usecs": "1282",
        "hypervisor_kvm_cpu_usage_ppm": "20685",
        "content_cache_physical_ssd_usage_bytes": "0",
        "controller_random_io_ppm": "-1",
        "controller_avg_read_io_size_kbytes": "0",
        "total_transformed_usage_bytes": "-1",
        "avg_write_io_latency_usecs": "-1",
        "num_read_io": "2",
        "write_io_bandwidth_kBps": "0",
        "hypervisor_read_io_bandwidth_kBps": "0",
        "random_io_ppm": "-1",
        "content_cache_num_hits": "0",
        "total_untransformed_usage_bytes": "-1",
        "hypervisor_total_io_time_usecs": "0",
        "num_random_io": "-1",
        "hypervisor_kvm_memory_usage_ppm": "278573",
        "controller_avg_write_io_size_kbytes": "0",
        "controller_avg_read_io_latency_usecs": "0",
        "num_write_io": "2",
        "hypervisor_esx_cpu_usage_ppm": "-1",
        "total_io_size_kbytes": "28",
        "io_bandwidth_kBps": "0",
        "content_cache_physical_memory_usage_bytes": "169834120",
        "replication_num_received_bytes": "0",
        "controller_timespan_usecs": "30000000",
        "num_seq_io": "-1",
        "content_cache_saved_memory_usage_bytes": "0",
        "seq_io_ppm": "-1",
        "write_io_ppm": "500000",
        "controller_avg_write_io_latency_usecs": "0",
        "content_cache_logical_memory_usage_bytes": "169834120"
      }},
      "usage_stats": {{
        "data_reduction.overall.saving_ratio_ppm": "-1",
        "storage.reserved_free_bytes": "0",
        "storage_tier.das-sata.usage_bytes": "0",
        "data_reduction.compression.saved_bytes": "-1",
        "data_reduction.saving_ratio_ppm": "-1",
        "data_reduction.erasure_coding.post_reduction_bytes": "-1",
        "storage_tier.ssd.pinned_usage_bytes": "0",
        "storage.reserved_usage_bytes": "0",
        "data_reduction.erasure_coding.saving_ratio_ppm": "-1",
        "data_reduction.thin_provision.saved_bytes": "-1",
        "storage_tier.das-sata.capacity_bytes": "0",
        "storage_tier.das-sata.free_bytes": "0",
        "storage.usage_bytes": "271417344",
        "data_reduction.erasure_coding.saved_bytes": "-1",
        "data_reduction.compression.pre_reduction_bytes": "-1",
        "storage_tier.das-sata.pinned_usage_bytes": "0",
        "data_reduction.pre_reduction_bytes": "-1",
        "storage_tier.ssd.capacity_bytes": "192547704127",
        "data_reduction.clone.saved_bytes": "-1",
        "storage_tier.ssd.free_bytes": "192276286783",
        "data_reduction.dedup.pre_reduction_bytes": "-1",
        "data_reduction.erasure_coding.pre_reduction_bytes": "-1",
        "storage.capacity_bytes": "192547704127",
        "data_reduction.dedup.post_reduction_bytes": "-1",
        "data_reduction.clone.saving_ratio_ppm": "-1",
        "storage.logical_usage_bytes": "300941312",
        "data_reduction.saved_bytes": "-1",
        "storage.free_bytes": "192276286783",
        "storage_tier.ssd.usage_bytes": "271417344",
        "data_reduction.compression.post_reduction_bytes": "-1",
        "data_reduction.post_reduction_bytes": "-1",
        "data_reduction.dedup.saved_bytes": "-1",
        "data_reduction.overall.saved_bytes": "-1",
        "data_reduction.thin_provision.saving_ratio_ppm": "-1",
        "data_reduction.compression.saving_ratio_ppm": "-1",
        "data_reduction.dedup.saving_ratio_ppm": "-1",
        "storage_tier.ssd.pinned_bytes": "0",
        "storage.reserved_capacity_bytes": "0"
      }},
      "enforce_rackable_unit_aware_placement": false,
      "disable_degraded_node_monitoring": false,
      "common_criteria_mode": false,
      "enable_on_disk_dedup": null,
      "management_servers": null,
      "fault_tolerance_domain_type": "NODE"
    }}
  ]
}}
'''.format(**uuids)


HOSTS_JSON = '''{{
  "metadata": {{
    "grand_total_entities": 1,
    "total_entities": 1,
    "filter_criteria": "",
    "sort_criteria": "",
    "page": 1,
    "count": 1,
    "start_index": 1,
    "end_index": 1
  }},
  "entities": [
    {{
      "service_vmid": "cf76a19a-3ba2-4147-9f30-4f7786d81879::2",
      "uuid": "{host}",
      "disk_hardware_configs": {{
        "1": null,
        "2": {{
          "serial_number": "local-ssd-1",
          "disk_id": "cf76a19a-3ba2-4147-9f30-4f7786d81879::9",
          "disk_uuid": "3009bfd0-3075-47be-8562-a1e3d0075dcd",
          "location": 2,
          "bad": false,
          "mounted": true,
          "mount_path": "/home/nutanix/data/stargate-storage/disks/local-ssd-1",
          "model": "EphemeralDisk",
          "vendor": "Google",
          "boot_disk": true,
          "only_boot_disk": false,
          "under_diagnosis": false,
          "background_operation": null,
          "current_firmware_version": "1",
          "target_firmware_version": "1",
          "can_add_as_new_disk": false,
          "can_add_as_old_disk": false
        }},
        "3": null,
        "4": null,
        "5": null,
        "6": null
      }},
      "name": "hostname.domainname",
      "service_vmexternal_ip": "172.30.0.5",
      "service_vmnat_ip": null,
      "service_vmnat_port": null,
      "oplog_disk_pct": 10.2,
      "oplog_disk_size": 33577472090,
      "hypervisor_key": "172.30.0.4",
      "hypervisor_address": "172.30.0.4",
      "hypervisor_username": "root",
      "hypervisor_password": null,
      "backplane_ip": null,
      "controller_vm_backplane_ip": "172.30.0.5",
      "rdma_backplane_ips": null,
      "management_server_name": "172.30.0.4",
      "ipmi_address": null,
      "ipmi_username": null,
      "ipmi_password": null,
      "monitored": true,
      "position": {{
        "ordinal": 1,
        "name": "",
        "physical_position": null
      }},
      "serial": "172-30-0-5",
      "block_serial": "null",
      "block_model": "Null",
      "block_model_name": "null",
      "block_location": null,
      "host_maintenance_mode_reason": null,
      "hypervisor_state": "kAcropolisNormal",
      "metadata_store_status": "kNormalMode",
      "metadata_store_status_message": "Metadata store enabled on the node",
      "state": "NORMAL",
      "dynamic_ring_changing_node": null,
      "removal_status": [
        "NA"
      ],
      "vzone_name": "",
      "cpu_model": "Intel(R) Xeon(R) CPU @ 2.20GHz",
      "num_cpu_cores": 10,
      "num_cpu_threads": 20,
      "num_cpu_sockets": 1,
      "cpu_frequency_in_hz": 2200000000,
      "cpu_capacity_in_hz": 22000000000,
      "memory_capacity_in_bytes": 25139609600,
      "hypervisor_full_name": "Nutanix 20170830.122",
      "hypervisor_type": "kKvm",
      "num_vms": 4,
      "boot_time_in_usecs": 1551369016488454,
      "is_degraded": false,
      "failover_cluster_fqdn": null,
      "failover_cluster_node_state": null,
      "reboot_pending": false,
      "default_vm_location": null,
      "default_vm_storage_container_id": null,
      "default_vm_storage_container_uuid": null,
      "default_vhd_location": null,
      "default_vhd_storage_container_id": null,
      "default_vhd_storage_container_uuid": null,
      "bios_version": null,
      "bios_model": null,
      "bmc_version": null,
      "bmc_model": null,
      "hba_firmwares_list": null,
      "cluster_uuid": "{cluster}",
      "stats": {{
        "hypervisor_avg_io_latency_usecs": "0",
        "num_read_iops": "0",
        "hypervisor_write_io_bandwidth_kBps": "0",
        "timespan_usecs": "30000000",
        "controller_num_read_iops": "0",
        "read_io_ppm": "466666",
        "controller_num_iops": "0",
        "total_read_io_time_usecs": "-1",
        "controller_total_read_io_time_usecs": "0",
        "hypervisor_num_io": "0",
        "controller_total_transformed_usage_bytes": "-1",
        "hypervisor_cpu_usage_ppm": "14896",
        "controller_num_write_io": "0",
        "avg_read_io_latency_usecs": "-1",
        "content_cache_logical_ssd_usage_bytes": "0",
        "controller_total_io_time_usecs": "0",
        "controller_total_read_io_size_kbytes": "0",
        "controller_num_seq_io": "-1",
        "controller_read_io_ppm": "0",
        "content_cache_num_lookups": "15",
        "controller_total_io_size_kbytes": "0",
        "content_cache_hit_ppm": "1000000",
        "controller_num_io": "0",
        "hypervisor_avg_read_io_latency_usecs": "0",
        "content_cache_num_dedup_ref_count_pph": "100",
        "num_write_iops": "0",
        "controller_num_random_io": "0",
        "num_iops": "0",
        "hypervisor_num_read_io": "0",
        "hypervisor_total_read_io_time_usecs": "0",
        "controller_avg_io_latency_usecs": "0",
        "num_io": "15",
        "controller_num_read_io": "0",
        "hypervisor_num_write_io": "0",
        "controller_seq_io_ppm": "-1",
        "controller_read_io_bandwidth_kBps": "0",
        "controller_io_bandwidth_kBps": "0",
        "hypervisor_num_received_bytes": "0",
        "hypervisor_timespan_usecs": "29847775",
        "hypervisor_num_write_iops": "0",
        "total_read_io_size_kbytes": "88",
        "hypervisor_total_io_size_kbytes": "0",
        "avg_io_latency_usecs": "251",
        "hypervisor_num_read_iops": "0",
        "content_cache_saved_ssd_usage_bytes": "0",
        "controller_write_io_bandwidth_kBps": "0",
        "controller_write_io_ppm": "0",
        "hypervisor_avg_write_io_latency_usecs": "0",
        "hypervisor_num_transmitted_bytes": "0",
        "hypervisor_total_read_io_size_kbytes": "0",
        "read_io_bandwidth_kBps": "2",
        "hypervisor_memory_usage_ppm": "278481",
        "hypervisor_num_iops": "0",
        "hypervisor_io_bandwidth_kBps": "0",
        "controller_num_write_iops": "0",
        "total_io_time_usecs": "3770",
        "content_cache_physical_ssd_usage_bytes": "0",
        "controller_random_io_ppm": "-1",
        "controller_avg_read_io_size_kbytes": "0",
        "total_transformed_usage_bytes": "-1",
        "avg_write_io_latency_usecs": "-1",
        "num_read_io": "7",
        "write_io_bandwidth_kBps": "2",
        "hypervisor_read_io_bandwidth_kBps": "0",
        "random_io_ppm": "-1",
        "total_untransformed_usage_bytes": "-1",
        "hypervisor_total_io_time_usecs": "0",
        "num_random_io": "-1",
        "controller_avg_write_io_size_kbytes": "0",
        "controller_avg_read_io_latency_usecs": "0",
        "num_write_io": "8",
        "total_io_size_kbytes": "176",
        "io_bandwidth_kBps": "5",
        "content_cache_physical_memory_usage_bytes": "169834120",
        "controller_timespan_usecs": "10000000",
        "num_seq_io": "-1",
        "content_cache_saved_memory_usage_bytes": "0",
        "seq_io_ppm": "-1",
        "write_io_ppm": "533333",
        "controller_avg_write_io_latency_usecs": "0",
        "content_cache_logical_memory_usage_bytes": "169834120"
      }},
      "usage_stats": {{
        "storage_tier.das-sata.usage_bytes": "0",
        "storage.capacity_bytes": "192547704127",
        "storage.logical_usage_bytes": "300941312",
        "storage_tier.das-sata.capacity_bytes": "0",
        "storage.free_bytes": "192276286783",
        "storage_tier.ssd.usage_bytes": "271417344",
        "storage_tier.ssd.capacity_bytes": "192547704127",
        "storage_tier.das-sata.free_bytes": "0",
        "storage.usage_bytes": "271417344",
        "storage_tier.ssd.free_bytes": "192276286783"
      }},
      "has_csr": false,
      "host_nic_ids": [],
      "host_gpus": null,
      "gpu_driver_version": null,
      "host_type": "HYPER_CONVERGED",
      "key_management_device_to_certificate_status": {{}},
      "host_in_maintenance_mode": null
    }}
  ]
}}
'''.format(**uuids)


VMS_JSON = '''{{
  "metadata": {{
    "grand_total_entities": 1,
    "total_entities": 1,
    "count": 1,
    "start_index": 0,
    "end_index": 1
  }},
  "entities": [
    {{
      "allow_live_migrate": true,
      "gpus_assigned": false,
      "ha_priority": 0,
      "host_uuid": "{host}",
      "memory_mb": 2048,
      "name": "VM3",
      "num_cores_per_vcpu": 1,
      "num_vcpus": 1,
      "power_state": "on",
      "timezone": "UTC",
      "uuid": "{vm}",
      "vm_features": {{
        "AGENT_VM": false,
        "VGA_CONSOLE": true
      }},
      "vm_logical_timestamp": 3
    }}
  ]
}}
'''.format(**uuids)

class TestNutanix(TestBase):
    @staticmethod
    def create_config(name, wrapper, **kwargs):
        config = NutanixConfigSection(name, wrapper)
        config.update(**kwargs)
        config.validate()
        return config

    def setUp(self):
        config = self.create_config(name='test', wrapper=None, type='nutanix',
                                    server='localhost', username='username',
                                    password=u'1€345678', owner='owner',
                                    env='env', ssl_verify='False')

        self.nutanix = Virt.from_config(self.logger, config, Datastore())
        self.nutanix.prepare()

    def run_once(self, queue=None):
        """Run Nutanix in oneshot mode"""
        self.nutanix._oneshot = True
        self.nutanix.dest = queue or Queue()
        self.nutanix._terminate_event = Event()
        self.nutanix._oneshot = True
        self.nutanix._interval = 0
        self.nutanix._run()

    @patch('requests.get')
    def test_connect(self, get):
        get.return_value.content = '{}'
        get.return_value.status_code = 200
        self.run_once()

        self.assertEqual(get.call_count, 3)
        get.assert_has_calls([
            call('https://localhost:9440/PrismGateway/services/rest/v2.0/clusters', auth=ANY, verify=ANY),
            call().raise_for_status(),
            call('https://localhost:9440/PrismGateway/services/rest/v2.0/hosts', auth=ANY, verify=ANY),
            call().raise_for_status(),
            call('https://localhost:9440/PrismGateway/services/rest/v2.0/vms', auth=ANY, verify=ANY),
            call().raise_for_status(),
        ])
        self.assertEqual(get.call_args[1]['auth'].username, u'username'.encode('utf-8'))
        self.assertEqual(get.call_args[1]['auth'].password, u'1€345678'.encode('utf-8'))

    @patch('requests.get')
    def test_connection_refused(self, get):
        get.return_value.post.side_effect = requests.ConnectionError
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_invalid_login(self, get):
        get.return_value.status_code = 401
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_404(self, get):
        get.return_value.content = ''
        get.return_value.status_code = 404
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_500(self, get):
        get.return_value.content = ''
        get.return_value.status_code = 500
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_getHostGuestMapping(self, get):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = uuids['host']
        expected_guestId = uuids['vm']
        expected_guest_state = Guest.STATE_RUNNING

        get.side_effect = [
            MagicMock(content=CLUSTERS_JSON),
            MagicMock(content=HOSTS_JSON),
            MagicMock(content=VMS_JSON),
        ]

        expected_result = Hypervisor(
            hypervisorId=expected_hypervisorId,
            name=expected_hostname,
            guestIds=[
                Guest(
                    expected_guestId,
                    self.nutanix.CONFIG_TYPE,
                    expected_guest_state,
                )
            ],
            facts={
                Hypervisor.CPU_SOCKET_FACT: '1',
                Hypervisor.HYPERVISOR_TYPE_FACT: 'nutanix',
                Hypervisor.HYPERVISOR_CLUSTER: 'Cetus',
                Hypervisor.SYSTEM_UUID_FACT: uuids['host'],
            }
        )
        result = self.nutanix.getHostGuestMapping()['hypervisors'][0]
        self.assertEqual(expected_result.toDict(), result.toDict())

    def test_proxy(self):
        proxy = Proxy()
        self.addCleanup(proxy.terminate)
        proxy.start()
        oldenv = os.environ.copy()
        self.addCleanup(lambda: setattr(os, 'environ', oldenv))
        os.environ['https_proxy'] = proxy.address

        self.assertRaises(VirtError, self.run_once)
        self.assertIsNotNone(proxy.last_path, "Proxy was not called")
        self.assertEqual(proxy.last_path, 'localhost:9440')

    @patch('requests.get')
    def test_new_status(self, get):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = uuids['host']
        expected_guestId = uuids['vm']
        expected_guest_state = Guest.STATE_RUNNING

        get.side_effect = [
            MagicMock(content=CLUSTERS_JSON),
            MagicMock(content=HOSTS_JSON),
        ]

        expected_result = Hypervisor(
            hypervisorId=expected_hypervisorId,
            name=expected_hostname,
            guestIds=[
                Guest(
                    expected_guestId,
                    self.nutanix.CONFIG_TYPE,
                    expected_guest_state,
                )
            ],
            facts={
                Hypervisor.CPU_SOCKET_FACT: '1',
                Hypervisor.HYPERVISOR_TYPE_FACT: 'nutanix',
                Hypervisor.HYPERVISOR_CLUSTER: 'Cetus',
                Hypervisor.SYSTEM_UUID_FACT: uuids['host'],
            }
        )
        result = self.nutanix.getHostGuestMapping()['hypervisors'][0]
        self.assertEqual(expected_result.toDict(), result.toDict())
