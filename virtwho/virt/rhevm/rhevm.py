# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Module for communication with RHEV-M, part of virt-who

Copyright (C) 2012 Radek Novacek <rnovacek@redhat.com>

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
from xml.etree import ElementTree

from virtwho import virt
from virtwho.config import VirtConfigSection


RHEVM_STATE_TO_GUEST_STATE = {
    'unassigned': virt.Guest.STATE_UNKNOWN,
    'down': virt.Guest.STATE_SHUTOFF,
    'up': virt.Guest.STATE_RUNNING,
    'powering_up': virt.Guest.STATE_SHUTOFF,
    'powered_down': virt.Guest.STATE_SHUTINGDOWN,
    'paused': virt.Guest.STATE_PAUSED,
    'migrating_from': virt.Guest.STATE_SHUTOFF,
    'migrating_to': virt.Guest.STATE_SHUTOFF,
    'unknown': virt.Guest.STATE_UNKNOWN,
    'not_responding': virt.Guest.STATE_BLOCKED,
    'wait_for_launch': virt.Guest.STATE_BLOCKED,
    'reboot_in_progress': virt.Guest.STATE_SHUTOFF,
    'saving_state': virt.Guest.STATE_SHUTINGDOWN,
    'restoring_state': virt.Guest.STATE_SHUTOFF,
    'suspended': virt.Guest.STATE_PMSUSPENDED,
    'image_illegal': virt.Guest.STATE_CRASHED,
    'image_locked': virt.Guest.STATE_CRASHED,
    'powering_down': virt.Guest.STATE_SHUTINGDOWN
}


class RhevmConfigSection(VirtConfigSection):
    """
    This class is used for validation of RHEVM virtualization backend
    section. It tries to validate options and combination of options that
    are specific for this virtualization backend.
    """

    VIRT_TYPE = 'rhevm'
    HYPERVISOR_ID = ('uuid', 'hwuuid', 'hostname')

    def __init__(self, section_name, wrapper, *args, **kwargs):
        super(RhevmConfigSection, self).__init__(section_name, wrapper, *args, **kwargs)
        self.add_key('server', validation_method=self._validate_server, required=True)
        self.add_key('username', validation_method=self._validate_username, required=True)
        self.add_key('password', validation_method=self._validate_unencrypted_password, required=True)

    def _validate_server(self, key='server'):
        """
        Do validation of server option specific for this virtualization backend
        return: Return None or info/warning/error
        """
        url = self._values[key]

        if "//" not in url:
            url = "//" + url
        parsed = urllib.parse.urlsplit(url, "https")
        if ":" not in parsed[1]:
            netloc = parsed[1] + ":8443"
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
        else:
            return None


class RhevM(virt.Virt):
    CONFIG_TYPE = "rhevm"

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(RhevM, self).__init__(logger, config, dest,
                                    terminate_event=terminate_event,
                                    interval=interval,
                                    oneshot=oneshot)
        self.url = self.config['server']
        self.api_base = 'api'
        self.username = self.config['username']
        self.password = self.config['password']
        self.auth = HTTPBasicAuth(self.username.encode('utf-8'), self.password.encode('utf-8'))
        self.prepared = False
        self.clusters_url = None
        self.hosts_url = None
        self.vms_url = None

    def prepare(self):
        if not self.prepared:
            if not hasattr(self, 'major_version'):
                self.get_version()
            self.build_urls()
            self.prepared = True

    def build_urls(self):
        """
        Builds the URL's based on Rhev version
        """
        clusters_endpoint = '/clusters'
        hosts_endpoint = '/hosts'
        vms_endpoint = '/vms'

        self.clusters_url = urllib.parse.urljoin(self.url, self.api_base + clusters_endpoint)
        self.hosts_url = urllib.parse.urljoin(self.url, self.api_base + hosts_endpoint)
        self.vms_url = urllib.parse.urljoin(self.url, self.api_base + vms_endpoint)

    def get_version(self):
        """
        Gets the major version from the Rhevm server
        """
        try:
            headers = dict()
            headers['Version'] = '3'
            # We will store the api_base that seems to work and use that for future requests
            response = requests.get(urllib.parse.urljoin(self.url, self.api_base),
                                    auth=self.auth,
                                    headers=headers,
                                    verify=False)
            if response.status_code == 404:
                self.api_base = 'ovirt-engine/api'
                response = requests.get(urllib.parse.urljoin(self.url, self.api_base),
                                        auth=self.auth,
                                        headers=headers,
                                        verify=False)
            response.raise_for_status()
        except requests.RequestException as e:
            raise virt.VirtError("Unable to connect to RHEV-M server: %s" % str(e))

        try:
            api = ElementTree.fromstring(response.content)
        except Exception as e:
            self.logger.debug("Invalid xml file: %s" % response)
            raise virt.VirtError("Invalid XML file returned from RHEV-M: %s" % str(e))
        version = api.find('.//version')
        if version is not None:
            major = version.attrib['major']
            self.major_version = major
        else:
            self.logger.info("Could not determine version")

    def get(self, url):
        """
        Call RHEV-M server and retrieve what's on given url.
        """
        try:
            if self.major_version == '4':
                # If we are talking to a Rhev4 system, we need to specifically request
                # the Rhev 3 version of the api.  To minimize code impact, we do this
                # by setting a 'Version' header, as outlined in Rhev 4's "Version 3
                # REST API Guide"
                headers = dict()
                headers['Version'] = '3'
                response = requests.get(url, auth=self.auth, verify=False, headers=headers)
            else:
                response = requests.get(url, auth=self.auth, verify=False)
            response.raise_for_status()
        except requests.RequestException as e:
            raise virt.VirtError("Unable to connect to RHEV-M server: %s" % str(e))
        # FIXME: other errors
        return response.content

    def get_xml(self, url):
        """
        Call RHEV-M server, retrieve XML and parse it.
        """
        response = self.get(url)
        try:
            return ElementTree.fromstring(response)
        except Exception as e:
            self.logger.debug("Invalid xml file: %s" % response)
            raise virt.VirtError("Invalid XML file returned from RHEV-M: %s" % str(e))

    def getHostGuestMapping(self):
        """
        Returns dictionary containing a list of virt.Hypervisors
        Each virt.Hypervisor contains the hypervisor ID as well as a list of
        virt.Guest

        {'hypervisors': [Hypervisor1, ...]
        }
        """
        mapping = {}
        hosts = {}
        clusters = set()
        cluster_names = {}

        clusters_xml = self.get_xml(self.clusters_url)
        hosts_xml = self.get_xml(self.hosts_url)
        vms_xml = self.get_xml(self.vms_url)

        # Save ids of clusters that are "virt_service"
        for cluster in clusters_xml.findall('cluster'):
            cluster_id = cluster.get('id')
            virt_service = cluster.find('virt_service').text
            cluster_names[cluster_id] = cluster.find('name').text
            if virt_service.lower() == 'true':
                clusters.add(cluster_id)

        for host in hosts_xml.findall('host'):
            id = host.get('id')
            system_uuid = ''
            # Check if host is in cluster that is "virt_service"
            host_cluster = host.find('cluster')
            host_cluster_id = host_cluster.get('id')
            if host_cluster_id not in clusters:
                # Skip the host if it's cluster is not "virt_service"
                self.logger.debug('Cluster of host %s is not virt_service, skipped', id)
                continue

            try:
                system_uuid = host.find('hardware_information').find('uuid').text
            except AttributeError:
                # The error is not important yet
                self.logger.info("Unable to get hardware uuid for host %s ", id)


            if self.config['hypervisor_id'] == 'uuid':
                host_id = id
            elif self.config['hypervisor_id'] == 'hwuuid':
                if not system_uuid == '':
                    host_id = system_uuid
                else:
                    self.logger.error("Host %s doesn't have hardware uuid", id)
                    continue
            elif self.config['hypervisor_id'] == 'hostname':
                host_id = host.find('address').text

            sockets = host.find('cpu').find('topology').get('sockets')
            if not sockets:
                try:
                    sockets = host.find('cpu').find('topology').find('sockets').text
                except AttributeError:
                    sockets = "unknown"

            facts = {
                virt.Hypervisor.CPU_SOCKET_FACT: sockets,
                virt.Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                virt.Hypervisor.SYSTEM_UUID_FACT: system_uuid,
            }

            try:
                cluster_name = cluster_names[host_cluster_id]
            except KeyError:
                pass
            else:
                facts[virt.Hypervisor.HYPERVISOR_CLUSTER] = cluster_name

            try:
                version = host.find('version').get('full_version')
                if version:
                    facts[virt.Hypervisor.HYPERVISOR_VERSION_FACT] = version
            except AttributeError:
                pass

            hosts[id] = virt.Hypervisor(hypervisorId=host_id, name=host.find('address').text, facts=facts)
            mapping[id] = []
        for vm in vms_xml.findall('vm'):
            guest_id = vm.get('id')
            host = vm.find('host')
            if host is None:
                # Guest don't have any host
                continue

            host_id = host.get('id')
            if host_id not in mapping.keys():
                self.logger.warning(
                    "Guest %s claims that it belongs to host %s which doesn't exist",
                    guest_id, host_id)
                continue

            try:
                status = vm.find('status')
                try:
                    state_text = status.find('state').text.lower()
                except AttributeError:
                    # RHEVM 4.0 reports the state differently
                    state_text = status.text.lower()
                state = RHEVM_STATE_TO_GUEST_STATE.get(state_text, virt.Guest.STATE_UNKNOWN)
            except AttributeError:
                self.logger.warning(
                    "Guest %s doesn't report any status",
                    guest_id)
                state = virt.Guest.STATE_UNKNOWN

            hosts[host_id].guestIds.append(virt.Guest(guest_id, self.CONFIG_TYPE, state))

        return {'hypervisors': list(hosts.values())}

    def ping(self):
        return True

