# -*- coding: utf-8 -*-
# pylint: disable=C0103,C0301,C0413,missing-docstring

from __future__ import print_function
"""
Module for communication with Nutanix

Copyright (C) 2019 Joshua Preston <mrjoshuap@redhat.com>

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

from six.moves import urllib
import requests
from requests.auth import HTTPBasicAuth
import json

from virtwho import virt
from virtwho.config import VirtConfigSection


NUTANIX_STATE_TO_GUEST_STATE = {
    'unknown': virt.Guest.STATE_UNKNOWN,
    'off': virt.Guest.STATE_SHUTOFF,
    'powering_on': virt.Guest.STATE_SHUTOFF,
    'on': virt.Guest.STATE_RUNNING,
    'shutting_down': virt.Guest.STATE_SHUTINGDOWN,
    'powering_off': virt.Guest.STATE_SHUTINGDOWN,
    'pausing': virt.Guest.STATE_PAUSED,
    'paused': virt.Guest.STATE_PAUSED,
    'suspending': virt.Guest.STATE_PMSUSPENDED,
    'suspended': virt.Guest.STATE_PMSUSPENDED,
    'resuming': virt.Guest.STATE_SHUTOFF,
    'resetting': virt.Guest.STATE_SHUTOFF,
    'migrating': virt.Guest.STATE_SHUTOFF,
}


class NutanixConfigSection(VirtConfigSection):
    """
    This class is used for validation of NUTANIX virtualization backend
    section. It tries to validate options and combination of options that
    are specific for this virtualization backend.
    """

    VIRT_TYPE = 'nutanix'
    HYPERVISOR_ID = ('uuid', 'hwuuid', 'hostname')

    def __init__(self, section_name, wrapper, *args, **kwargs):
        super(NutanixConfigSection, self).__init__(section_name, wrapper, *args, **kwargs)
        self.add_key('server', validation_method=self._validate_server, required=True)
        self.add_key('username', validation_method=self._validate_username, required=True)
        self.add_key('password', validation_method=self._validate_unencrypted_password, required=True)
        self.add_key('filter_host_parents', validation_method=self._validate_filter, default=None)
        self.add_key('exclude_host_parents', validation_method=self._validate_filter, default=None)
        self.add_key('ssl_verify', validation_method=self._validate_str_to_bool, default=True)
        self.add_key('api_base', validation_method=self._validate_str_to_bool, default=True)

    def _validate_server(self, key='server'):
        """
        Do validation of server option specific for this virtualization backend
        return: Return None or info/warning/error
        """
        if not self._values[key] or self._values[key] == "":
            return [(
                'error',
                "Nutanix server is not specified"
            )]

        url = self._values[key]

        if "//" not in url:
            url = "//" + url
        parsed = urllib.parse.urlsplit(url, "https")
        if ":" not in parsed[1]:
            netloc = parsed[1] + ":9440"
        else:
            netloc = parsed[1]
        url = urllib.parse.urlunsplit((parsed[0], netloc, parsed[2], "", ""))

        if url[-1] != '/':
            url += '/'

        if url != self._values[key]:
            self._values[key] = url
            return [(
                'info',
                "The original server URL was incomplete. It has been enhanced to %s" % url
            )]

        return None

class Nutanix(virt.Virt):
    CONFIG_TYPE = "nutanix"

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(Nutanix, self).__init__(logger, config, dest,
                                      terminate_event=terminate_event,
                                      interval=interval,
                                      oneshot=oneshot)
        # Default: ""
        self.server = self.config['server']

        # Default: True
        self.ssl_verify = self.config['ssl_verify']

        # Default: /PrismGateway/services/rest/v2.0/
        self.api_base = self.config['api_base']

        # Default: ""
        self.username = self.config['username']

        # Default: ""
        self.password = self.config['password']

        self.auth = HTTPBasicAuth(self.username.encode('utf-8'), self.password.encode('utf-8'))
        self.prepared = False

        self.clusters_url = None
        self.hosts_url = None
        self.vms_url = None

    def prepare(self):
        if not self.prepared:
            self.build_urls()
            self.prepared = True

    def build_urls(self):
        """
        Builds the URL's based on Nutanix version 2 API

        See https://developer.nutanix.com/reference/prism_element/v2/api/
        """
        # https://developer.nutanix.com/reference/prism_element/v2/api/clusters/get-clusters-getclusters
        clusters_endpoint = self.api_base + '/clusters'
        self.clusters_url = urllib.parse.urljoin(self.server, clusters_endpoint)

        # https://developer.nutanix.com/reference/prism_element/v2/api/hosts/get-hosts-gethosts
        hosts_endpoint = self.api_base + '/hosts'
        self.hosts_url = urllib.parse.urljoin(self.server, hosts_endpoint)

        # https://developer.nutanix.com/reference/prism_element/v2/api/vms/get-vms-getvms
        vms_endpoint = self.api_base + '/vms'
        self.vms_url = urllib.parse.urljoin(self.server, vms_endpoint)

    def get(self, url):
        """
        Call Nutanix and retrieve what's on given url.  Currently does not paginate.
        """
        try:
            headers = dict()
            response = requests.get(url, auth=self.auth, verify=self.ssl_verify, headers=headers)
            response.raise_for_status()
        except requests.RequestException as e:
            raise virt.VirtError("Unable to connect to Nutanix server: %s" % str(e))
        # FIXME: other errors

        response_json = json.loads(response.content)
        if 'metadata' in response_json.keys():
            grand_total_entities = response_json['metadata']['grand_total_entities']
            count = response_json['metadata']['count']
            if grand_total_entities != count:
                self.logger.error('Nutanix module does not yet support multi-page result sets')

        return response_json

    def getHostGuestMapping(self):
        """
        Returns dictionary containing a list of virt.Hypervisors
        Each virt.Hypervisor contains the hypervisor ID as well as a list of
        virt.Guest

        {'hypervisors': [Hypervisor1, ...]
        }
        """
        clusters = set()
        cluster_names = {}
        hosts = {}
        host_names = {}
        mapping = {}

        clusters_json = self.get(self.clusters_url)
        hosts_json = self.get(self.hosts_url)
        vms_json = self.get(self.vms_url)

        # Find all the clusters
        for cluster in clusters_json['entities']:
            cluster_uuid = cluster['uuid']
            cluster_names[cluster_uuid] = cluster['name']
            clusters.add(cluster_uuid)

        # Find all the hosts
        for host in hosts_json['entities']:
            host_uuid = host['uuid']
            host_cluster_uuid = host['cluster_uuid']

            if self.config['exclude_host_parents'] is not None and host_uuid in self.config['exclude_host_parents']:
                self.logger.debug("Skipping host '%s' because its excluded", host_uuid)
                continue

            if self.config['filter_host_parents'] is not None and host_uuid not in self.config['filter_host_parents']:
                self.logger.debug("Skipping host '%s' because its not included", host_uuid)
                continue

            if host_cluster_uuid not in clusters:
                # Skip the host if it's cluster is not found
                self.logger.info('Cluster of host %s is not found, skipped', host_uuid)
                continue

            sockets = host['num_cpu_sockets']
            if not sockets:
                sockets = "unknown"

            hypervisor_type = host['hypervisor_type']
            if not hypervisor_type:
                hypervisor_type = "nutanix"

            facts = {
                virt.Hypervisor.CPU_SOCKET_FACT: sockets,
                virt.Hypervisor.HYPERVISOR_TYPE_FACT: hypervisor_type,
                virt.Hypervisor.SYSTEM_UUID_FACT: host_uuid,
            }

            try:
                cluster_name = cluster_names[host_cluster_uuid]
            except KeyError:
                pass
            else:
                facts[virt.Hypervisor.HYPERVISOR_CLUSTER] = cluster_name

            hosts[host_uuid] = virt.Hypervisor(hypervisorId=host_uuid, name=host['name'], facts=facts)
            mapping[host_uuid] = []

        # find all the vms
        for vm in vms_json['entities']:
            guest_id = vm['uuid']
            host_uuid = vm['host_uuid']

            if self.config['exclude_host_parents'] is not None and host_uuid in self.config['exclude_host_parents']:
                self.logger.debug("Skipping guest '%s' because its host '%s' is excluded", guest_id, host_uuid)
                continue

            if self.config['filter_host_parents'] is not None and host_uuid not in self.config['filter_host_parents']:
                self.logger.debug("Skipping guest '%s' because its host '%s' is not included", guest_id, host_uuid)
                continue

            if host_uuid is None:
                # Guest don't have any host
                self.logger.info('Host of guest %s is not found, skipped', guest_id)
                continue

            if host_uuid not in mapping.keys():
                self.logger.warning(
                    "Guest %s claims that it belongs to host %s which doesn't exist",
                    guest_id, host_uuid)
                continue

            try:
                status = vm['status']
                state = NUTANIX_STATE_TO_GUEST_STATE.get(status, virt.Guest.STATE_UNKNOWN)
            except AttributeError:
                self.logger.warning(
                    "Guest %s doesn't report any status",
                    guest_id)
                state = virt.Guest.STATE_UNKNOWN

            hosts[host_uuid].guestIds.append(virt.Guest(guest_id, self.CONFIG_TYPE, state))

        return {'hypervisors': list(hosts.values())}

    def listDomains(self):
        return True

    def ping(self):
        return True
