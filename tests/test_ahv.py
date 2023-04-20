#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

from __future__ import print_function

from base import TestBase
from mock import patch, call, ANY, Mock
from requests import Session
from queue import Queue
from threading import Event

from virtwho import DefaultInterval
from virtwho import virt
from virtwho.datastore import Datastore
from virtwho.virt.ahv.ahv import AhvConfigSection
from virtwho.virt import Virt, VirtError, Guest, Hypervisor, StatusReport


MY_SECTION_NAME = 'test-ahv'
DefaultUpdateInterval = 1800
# Values used for testing AhvConfigSection.
PE_SECTION_VALUES = {
    'type': 'ahv',
    'server': '10.10.10.10',
    'username': 'root',
    'password': 'root_password',
    'owner': 'nutanix',
    'prism_central': False,
    'hypervisor_id': 'uuid',
    'is_hypervisor': True,
    'ahv_internal_debug': False,
}

CLUSTER_NAMES = [("0005809e-62e4-75c7-611b-0cc47ac3b354", "cluster_1")]
CLUSTER_NAMES_BLANK = []

HOST_UVM_MAP = {
    "08469de5-be42-43e6-8c32-20167d3b58f7": {
        "oplog_disk_pct": 3.4,
        "memory_capacity_in_bytes": 135009402880,
        "has_csr": False,
        "default_vm_storage_container_uuid": None,
        "hypervisor_username": "root",
        "key_management_device_to_certificate_status": {},
        "service_vmnat_ip": None,
        "hypervisor_key": "10.53.97.188",
        "acropolis_connection_state": "kConnected",
        "management_server_name": "10.53.97.188",
        "failover_cluster_fqdn": None,
        "serial": "OM155S016008",
        "bmc_version": "01.92",
        "hba_firmwares_list": [
            {
                "hba_model": "LSI Logic SAS3008",
                "hba_version": "MPTFW-06.00.00.00-IT",
            }
        ],
        "hypervisor_state": "kAcropolisNormal",
        "num_cpu_threads": 32,
        "monitored": True,
        "uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
        "reboot_pending": False,
        "cpu_capacity_in_hz": 38384000000,
        "num_cpu_sockets": 2,
        "host_maintenance_mode_reason": None,
        "hypervisor_address": "10.53.97.188",
        "host_gpus": None,
        "failover_cluster_node_state": None,
        "state": "NORMAL",
        "num_cpu_cores": 16,
        "guest_list": [
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am2",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 48,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "01dcfc0b-3092-4f1b-94fb-81b44ed352be",
            },
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am3",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 3,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "422f9171-db1f-48b0-a3de-b0bb92a8f559",
            },
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "win_vm",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 3,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "98839f35-bd62-4255-a7cd-7668bc143554",
            },
        ],
        "cpu_model": "Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz",
        "ipmi_username": "ADMIN",
        "service_vmid": "0005809e-62e4-75c7-611b-0cc47ac3b354::7",
        "bmc_model": "X10_ATEN",
        "host_nic_ids": [],
        "cluster_uuid": "0005809e-62e4-75c7-611b-0cc47ac3b354",
        "ipmi_password": None,
        "cpu_frequency_in_hz": 2399000000,
        "stats": {
            "num_read_io": "8",
            "controller_read_io_bandwidth_kBps": "0",
            "content_cache_hit_ppm": "1000000",
        },
        "num_vms": 4,
        "default_vm_storage_container_id": None,
        "metadata_store_status": "kNormalMode",
        "name": "foyt-4",
        "hypervisor_password": None,
        "service_vmnat_port": None,
        "hypervisor_full_name": "Nutanix 20180802.100874",
        "is_degraded": False,
        "host_type": "HYPER_CONVERGED",
        "default_vhd_storage_container_uuid": None,
        "block_serial": "15SM60250038",
        "disk_hardware_configs": {
            "1": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC506101XL480MGN",
            },
            "3": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E6QE",
            },
            "2": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC50610246480MGN",
            },
            "5": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E835",
            },
            "4": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E8B1",
            },
            "6": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E7B3",
            },
        },
        "ipmi_address": "10.49.27.28",
        "bios_model": "0824",
        "default_vm_location": None,
        "hypervisor_type": "kKvm",
        "service_vmexternal_ip": "10.53.97.192",
        "controller_vm_backplane_ip": "10.53.97.192",
    },
    "54830446-b55e-4f16-aa74-7b6a9ac9a7a4": {
        "oplog_disk_pct": 3.4,
        "memory_capacity_in_bytes": 135009402880,
        "has_csr": False,
        "default_vm_storage_container_uuid": None,
        "hypervisor_username": "root",
        "service_vmnat_ip": None,
        "hypervisor_key": "10.53.97.187",
        "acropolis_connection_state": "kConnected",
        "hypervisor_state": "kAcropolisNormal",
        "num_cpu_threads": 32,
        "monitored": True,
        "uuid": "54830446-b55e-4f16-aa74-7b6a9ac9a7a4",
        "reboot_pending": False,
        "cpu_capacity_in_hz": 38384000000,
        "num_cpu_sockets": 2,
        "host_maintenance_mode_reason": None,
        "hypervisor_address": "10.53.97.187",
        "host_gpus": None,
        "failover_cluster_node_state": None,
        "state": "NORMAL",
        "num_cpu_cores": 16,
        "block_model": "UseLayout",
        "guest_list": [
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "PC",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 4,
                "memory_mb": 16384,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "UTC",
                "vm_logical_timestamp": 10,
                "host_uuid": "54830446-b55e-4f16-aa74-7b6a9ac9a7a4",
                "uuid": "d90b5443-97f0-47eb-986d-f14e062448d4",
            },
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am1",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 14,
                "host_uuid": "54830446-b55e-4f16-aa74-7b6a9ac9a7a4",
                "uuid": "0af0a010-0ad0-4fba-aa33-7cc3d0b6cb7e",
            },
        ],
        "cpu_model": "Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz",
        "ipmi_username": "ADMIN",
        "service_vmid": "0005809e-62e4-75c7-611b-0cc47ac3b354::6",
        "bmc_model": "X10_ATEN",
        "host_nic_ids": [],
        "cluster_uuid": "0005809e-62e4-75c7-611b-0cc47ac3b354",
        "stats": {
            "num_read_io": "27",
            "controller_read_io_bandwidth_kBps": "0",
            "content_cache_hit_ppm": "1000000",
        },
        "backplane_ip": None,
        "vzone_name": "",
        "default_vhd_location": None,
        "metadata_store_status_message": "Metadata store enabled on the node",
        "num_vms": 3,
        "default_vm_storage_container_id": None,
        "metadata_store_status": "kNormalMode",
        "name": "foyt-3",
        "hypervisor_password": None,
        "service_vmnat_port": None,
        "hypervisor_full_name": "Nutanix 20180802.100874",
        "is_degraded": False,
        "host_type": "HYPER_CONVERGED",
        "default_vhd_storage_container_uuid": None,
        "block_serial": "15SM60250038",
        "disk_hardware_configs": {
            "1": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC506101ST480MGN",
            },
            "3": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8DXYY",
            },
            "2": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC506101D4480MGN",
            },
            "5": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8DQRM",
            },
            "4": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8DJ7E",
            },
            "6": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8DVGG",
            },
        },
        "ipmi_address": "10.49.27.27",
        "bios_model": "0824",
        "hypervisor_type": "kKvm",
        "service_vmexternal_ip": "10.53.97.191",
        "controller_vm_backplane_ip": "10.53.97.191",
    },
    "acc819fe-e0ff-4963-93a4-5a0e1d3c77d3": {
        "oplog_disk_pct": 3.4,
        "memory_capacity_in_bytes": 270302969856,
        "has_csr": False,
        "default_vm_storage_container_uuid": None,
        "hypervisor_username": "root",
        "key_management_device_to_certificate_status": {},
        "service_vmnat_ip": None,
        "hypervisor_key": "10.53.96.75",
        "acropolis_connection_state": "kConnected",
        "management_server_name": "10.53.96.75",
        "failover_cluster_fqdn": None,
        "serial": "ZM162S002621",
        "bmc_version": "01.97",
        "hba_firmwares_list": [
            {
                "hba_model": "LSI Logic SAS3008",
                "hba_version": "MPTFW-10.00.03.00-IT",
            }
        ],
        "hypervisor_state": "kAcropolisNormal",
        "num_cpu_threads": 32,
        "monitored": True,
        "uuid": "acc819fe-e0ff-4963-93a4-5a0e1d3c77d3",
        "num_cpu_sockets": 2,
        "host_maintenance_mode_reason": None,
        "hypervisor_address": "10.53.96.75",
        "guest_list": [
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am_RH_satellite",
                "num_cores_per_vcp": 2,
                "gpus_assigned": False,
                "num_vcpus": 4,
                "memory_mb": 16384,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 5,
                "host_uuid": "acc819fe-e0ff-4963-93a4-5a0e1d3c77d3",
                "uuid": "e30f381d-d4bc-4958-a88c-79448efe5112",
            },
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am4",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 2,
                "host_uuid": "acc819fe-e0ff-4963-93a4-5a0e1d3c77d3",
                "uuid": "f1e3362b-0377-4d70-bccd-63d2a1c09225",
            },
        ],
        "dynamic_ring_changing_node": None,
        "cpu_model": "Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz",
        "ipmi_username": "ADMIN",
        "cluster_uuid": "0005809e-62e4-75c7-611b-0cc47ac3b354",
        "ipmi_password": None,
        "cpu_frequency_in_hz": 2400000000,
        "stats": {
            "num_read_io": "47",
            "controller_read_io_bandwidth_kBps": "0",
            "content_cache_hit_ppm": "1000000",
        },
        "backplane_ip": None,
        "num_vms": 3,
        "name": "watermelon02-4",
        "hypervisor_password": None,
        "hypervisor_full_name": "Nutanix 20180802.100874",
        "is_degraded": False,
        "host_type": "HYPER_CONVERGED",
        "default_vhd_storage_container_uuid": None,
        "block_serial": "16AP60170033",
        "usage_stats": {},
        "disk_hardware_configs": {
            "1": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC549209M3480MGN",
            },
            "3": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG9TRZQ"
            },
            "2": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC550503XF480MGN",
            },
            "5": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG9TS0N",
            },
            "4": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG9TSF7",
            },
            "6": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG9TREW",
            },
        },
        "ipmi_address": "10.49.26.188",
        "bios_model": "0824",
        "default_vm_location": None,
        "hypervisor_type": "kKvm",
        "position": {"ordinal": 4, "physical_position": None, "name": ""},
        "service_vmexternal_ip": "10.53.96.79",
        "controller_vm_backplane_ip": "10.53.96.79",
    },
}

HOST_UVM_MAP_2 = {
    "08469de5-be42-43e6-8c32-20167d3b58f7": {
        "oplog_disk_pct": 3.4,
        "memory_capacity_in_bytes": 135009402880,
        "has_csr": False,
        "default_vm_storage_container_uuid": None,
        "hypervisor_username": "root",
        "key_management_device_to_certificate_status": {},
        "service_vmnat_ip": None,
        "hypervisor_key": "10.53.97.188",
        "acropolis_connection_state": "kConnected",
        "management_server_name": "10.53.97.188",
        "failover_cluster_fqdn": None,
        "serial": "OM155S016008",
        "bmc_version": "01.92",
        "hba_firmwares_list": [
            {
                "hba_model": "LSI Logic SAS3008",
                "hba_version": "MPTFW-06.00.00.00-IT",
            }
        ],
        "hypervisor_state": "kAcropolisNormal",
        "num_cpu_threads": 32,
        "monitored": True,
        "uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
        "reboot_pending": False,
        "cpu_capacity_in_hz": 38384000000,
        "num_cpu_sockets": 2,
        "host_maintenance_mode_reason": None,
        "hypervisor_address": "10.53.97.188",
        "host_gpus": None,
        "failover_cluster_node_state": None,
        "state": "NORMAL",
        "num_cpu_cores": 16,
        "guest_list": [
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am2",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 48,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "01dcfc0b-3092-4f1b-94fb-81b44ed352be",
            },
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am3",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 3,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "422f9171-db1f-48b0-a3de-b0bb92a8f559",
            },
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "win_vm",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 3,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "98839f35-bd62-4255-a7cd-7668bc143554",
            },
        ],
        "cpu_model": "Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz",
        "ipmi_username": "ADMIN",
        "service_vmid": "0005809e-62e4-75c7-611b-0cc47ac3b354::7",
        "bmc_model": "X10_ATEN",
        "host_nic_ids": [],
        "cluster_uuid": "0005809e-62e4-75c7-611b-0cc47ac3b350",
        "ipmi_password": None,
        "cpu_frequency_in_hz": 2399000000,
        "stats": {
            "num_read_io": "8",
            "controller_read_io_bandwidth_kBps": "0",
            "content_cache_hit_ppm": "1000000",
        },
        "num_vms": 4,
        "default_vm_storage_container_id": None,
        "metadata_store_status": "kNormalMode",
        "name": "foyt-4",
        "hypervisor_password": None,
        "service_vmnat_port": None,
        "hypervisor_full_name": "Nutanix 20180802.100874",
        "is_degraded": False,
        "host_type": "HYPER_CONVERGED",
        "default_vhd_storage_container_uuid": None,
        "block_serial": "15SM60250038",
        "disk_hardware_configs": {
            "1": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC506101XL480MGN",
            },
            "3": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E6QE",
            },
            "2": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC50610246480MGN",
            },
            "5": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E835",
            },
            "4": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E8B1",
            },
            "6": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E7B3",
            },
        },
        "ipmi_address": "10.49.27.28",
        "bios_model": "0824",
        "default_vm_location": None,
        "hypervisor_type": "kKvm",
        "service_vmexternal_ip": "10.53.97.192",
        "controller_vm_backplane_ip": "10.53.97.192",
    },
}

HOST_UVM_MAP_3 = {
    "08469de5-be42-43e6-8c32-20167d3b58f7": {
        "oplog_disk_pct": 3.4,
        "memory_capacity_in_bytes": 135009402880,
        "has_csr": False,
        "default_vm_storage_container_uuid": None,
        "hypervisor_username": "root",
        "key_management_device_to_certificate_status": {},
        "service_vmnat_ip": None,
        "hypervisor_key": "10.53.97.188",
        "acropolis_connection_state": "kConnected",
        "management_server_name": "10.53.97.188",
        "failover_cluster_fqdn": None,
        "serial": "OM155S016008",
        "bmc_version": "01.92",
        "hba_firmwares_list": [
            {
                "hba_model": "LSI Logic SAS3008",
                "hba_version": "MPTFW-06.00.00.00-IT",
            }
        ],
        "hypervisor_state": "kAcropolisNormal",
        "num_cpu_threads": 32,
        "monitored": True,
        "uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
        "reboot_pending": False,
        "cpu_capacity_in_hz": 38384000000,
        "num_cpu_sockets": 2,
        "host_maintenance_mode_reason": None,
        "hypervisor_address": "10.53.97.188",
        "host_gpus": None,
        "failover_cluster_node_state": None,
        "state": "NORMAL",
        "num_cpu_cores": 16,
        "guest_list": [
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am2",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 48,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "01dcfc0b-3092-4f1b-94fb-81b44ed352be",
            },
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "am3",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 3,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "422f9171-db1f-48b0-a3de-b0bb92a8f559",
            },
            {
                "vm_features": {"AGENT_VM": False, "VGA_CONSOLE": True},
                "name": "win_vm",
                "num_cores_per_vcp": 1,
                "gpus_assigned": False,
                "num_vcpus": 2,
                "memory_mb": 4096,
                "power_state": "on",
                "ha_priority": 0,
                "allow_live_migrate": True,
                "timezone": "America/Los_Angeles",
                "vm_logical_timestamp": 3,
                "host_uuid": "08469de5-be42-43e6-8c32-20167d3b58f7",
                "uuid": "98839f35-bd62-4255-a7cd-7668bc143554",
            },
        ],
        "cpu_model": "Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz",
        "ipmi_username": "ADMIN",
        "service_vmid": "0005809e-62e4-75c7-611b-0cc47ac3b354::7",
        "bmc_model": "X10_ATEN",
        "host_nic_ids": [],
        "cluster_uuid": None,
        "ipmi_password": None,
        "cpu_frequency_in_hz": 2399000000,
        "stats": {
            "num_read_io": "8",
            "controller_read_io_bandwidth_kBps": "0",
            "content_cache_hit_ppm": "1000000",
        },
        "num_vms": 4,
        "default_vm_storage_container_id": None,
        "metadata_store_status": "kNormalMode",
        "name": "foyt-4",
        "hypervisor_password": None,
        "service_vmnat_port": None,
        "hypervisor_full_name": "Nutanix 20180802.100874",
        "is_degraded": False,
        "host_type": "HYPER_CONVERGED",
        "default_vhd_storage_container_uuid": None,
        "block_serial": "15SM60250038",
        "disk_hardware_configs": {
            "1": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC506101XL480MGN",
            },
            "3": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E6QE",
            },
            "2": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/BTHC50610246480MGN",
            },
            "5": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E835",
            },
            "4": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E8B1",
            },
            "6": {
                "mount_path": "/home/nutanix/data/stargate-storage/disks/9XG8E7B3",
            },
        },
        "ipmi_address": "10.49.27.28",
        "bios_model": "0824",
        "default_vm_location": None,
        "hypervisor_type": "kKvm",
        "service_vmexternal_ip": "10.53.97.192",
        "controller_vm_backplane_ip": "10.53.97.192",
    },
}


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
        self.assertCountEqual(expected_result, result)


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

    @patch.object(Session, 'get')
    def test_status(self, mock_get):
        mock_get.return_value.status_code = 200
        self.ahv.status = True
        self.ahv._send_data = Mock()
        self.run_once()

        self.ahv._send_data.assert_called_once_with(data_to_send=ANY)
        self.assertTrue(isinstance(self.ahv._send_data.mock_calls[0].kwargs['data_to_send'], StatusReport))
        self.assertEqual(self.ahv._send_data.mock_calls[0].kwargs['data_to_send'].data['source']['server'], self.ahv.config['server'])

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

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface2.get_host_list', return_value=None)
    @patch.object(Session, 'get')
    def test_no_retry_http_erros_PE(self, mock_get, mock_get_host_list):
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 400
        mock_get.return_value.text = 'Bad Request'
        self.assertEqual(mock_get_host_list.return_value, None)

        mock_get.return_value.status_code = 404
        mock_get.return_value.text = 'Not Found Error'
        self.assertEqual(mock_get_host_list.return_value, None)

        mock_get.return_value.status_code = 500
        mock_get.return_value.text = 'Internal Server Error'
        self.assertEqual(mock_get_host_list.return_value, None)

        mock_get.return_value.status_code = 502
        mock_get.return_value.tex = 'Bad Gateway'
        self.assertEqual(mock_get_host_list.return_value, None)

        mock_get.return_value.status_code = 503
        mock_get.return_value.text = 'Service Unavailable '
        self.assertEqual(mock_get_host_list.return_value, None)

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface3.get_host_list', return_value=None)
    @patch.object(Session, 'post')
    def test_no_retry_http_erros_PC(self, mock_post, mock_get_host_list):
        self.setUp(is_pc=True)
        mock_post.return_value.ok = False
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = 'Bad Request'
        self.assertEqual(mock_get_host_list.return_value, None)

        mock_post.return_value.status_code = 404
        mock_post.return_value.text = 'Not Found Error'
        self.assertEqual(mock_get_host_list.return_value, None)

        mock_post.return_value.status_code = 500
        mock_post.return_value.text = 'Internal Server Error'
        self.assertEqual(mock_get_host_list.return_value, None)

        mock_post.return_value.status_code = 502
        mock_post.return_value.tex = 'Bad Gateway'
        self.assertEqual(mock_get_host_list.return_value, None)

        mock_post.return_value.status_code = 503
        mock_post.return_value.text = 'Service Unavailable '
        self.assertEqual(mock_get_host_list.return_value, None)

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface2.get_ahv_cluster_uuid_name_list')
    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface2.build_host_to_uvm_map')
    def test_getHostGuestMapping_v2(self, host_to_uvm_map, cluster_names):
        host_to_uvm_map.return_value = HOST_UVM_MAP
        cluster_names.return_value = CLUSTER_NAMES

        expected_result = []

        for host_uuid in HOST_UVM_MAP:
            host = HOST_UVM_MAP[host_uuid]
            hypervisor_id = host_uuid
            host_name = host['name']
            cluster_name = dict(CLUSTER_NAMES)[host['cluster_uuid']]
            guests = []
            for guest_vm in host['guest_list']:
                state = virt.Guest.STATE_RUNNING
                guests.append(Guest(guest_vm['uuid'], self.ahv.CONFIG_TYPE, state))

            facts = {
               Hypervisor.CPU_SOCKET_FACT: '2',
               Hypervisor.HYPERVISOR_TYPE_FACT: u'kKvm',
               Hypervisor.HYPERVISOR_VERSION_FACT: 'Nutanix 20180802.100874',
               Hypervisor.SYSTEM_UUID_FACT: str(host_uuid),
               Hypervisor.HYPERVISOR_CLUSTER: str(cluster_name)
            }

            expected_result.append(Hypervisor(
                name=host_name,
                hypervisorId=hypervisor_id,
                guestIds=guests,
                facts=facts
            ))

        result = self.ahv.getHostGuestMapping()['hypervisors']

        self.assertEqual(
            len(result),
            len(expected_result),
            'lists length do not match'
        )

        for index in range(0, len(result)):
            self.assertEqual(expected_result[index].toDict(), result[index].toDict())

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface2.get_ahv_cluster_uuid_name_list')
    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface2.build_host_to_uvm_map')
    def test_getHostGuestMapping_empty_cluster_name_v2(self, host_to_uvm_map, cluster_names):
        host_to_uvm_map.return_value = HOST_UVM_MAP_2
        cluster_names.return_value = CLUSTER_NAMES_BLANK

        expected_result = []

        for host_uuid in HOST_UVM_MAP_2:
            host = HOST_UVM_MAP_2[host_uuid]
            hypervisor_id = host_uuid
            host_name = host['name']
            cluster_name = host['cluster_uuid']
            guests = []
            for guest_vm in host['guest_list']:
                state = virt.Guest.STATE_RUNNING
                guests.append(Guest(guest_vm['uuid'], self.ahv.CONFIG_TYPE, state))

            facts = {
               Hypervisor.CPU_SOCKET_FACT: '2',
               Hypervisor.HYPERVISOR_TYPE_FACT: u'kKvm',
               Hypervisor.HYPERVISOR_VERSION_FACT: 'Nutanix 20180802.100874',
               Hypervisor.SYSTEM_UUID_FACT: str(host_uuid),
               Hypervisor.HYPERVISOR_CLUSTER: str(cluster_name),
            }

            expected_result.append(Hypervisor(
                name=host_name,
                hypervisorId=hypervisor_id,
                guestIds=guests,
                facts=facts
            ))

        result = self.ahv.getHostGuestMapping()['hypervisors']

        self.assertEqual(
            len(result),
            len(expected_result),
            'lists length do not match'
        )

        for index in range(0, len(result)):
            self.assertEqual(expected_result[index].toDict(), result[index].toDict())

    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface2.get_ahv_cluster_uuid_name_list')
    @patch('virtwho.virt.ahv.ahv_interface.AhvInterface2.build_host_to_uvm_map')
    def test_getHostGuestMapping_no_cluster_uuid(self, host_to_uvm_map, cluster_names):
        host_to_uvm_map.return_value = HOST_UVM_MAP_3
        cluster_names.return_value = CLUSTER_NAMES_BLANK

        expected_result = []

        for host_uuid in HOST_UVM_MAP_3:
            host = HOST_UVM_MAP_3[host_uuid]
            hypervisor_id = host_uuid
            host_name = host['name']
            guests = []
            for guest_vm in host['guest_list']:
                state = virt.Guest.STATE_RUNNING
                guests.append(Guest(guest_vm['uuid'], self.ahv.CONFIG_TYPE, state))

            facts = {
               Hypervisor.CPU_SOCKET_FACT: '2',
               Hypervisor.HYPERVISOR_TYPE_FACT: u'kKvm',
               Hypervisor.HYPERVISOR_VERSION_FACT: 'Nutanix 20180802.100874',
               Hypervisor.SYSTEM_UUID_FACT: str(host_uuid)
            }

            expected_result.append(Hypervisor(
                name=host_name,
                hypervisorId=hypervisor_id,
                guestIds=guests,
                facts=facts
            ))

        result = self.ahv.getHostGuestMapping()['hypervisors']

        self.assertEqual(
            len(result),
            len(expected_result),
            'lists length do not match'
        )

        for index in range(0, len(result)):
            self.assertEqual(expected_result[index].toDict(), result[index].toDict())
