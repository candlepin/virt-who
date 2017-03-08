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

import sys
import urlparse
import requests
from requests.auth import HTTPBasicAuth
from xml.etree import ElementTree

from virtwho import virt
from virtwho.config import Config


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


class RhevM(virt.Virt):
    CONFIG_TYPE = "rhevm"

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(RhevM, self).__init__(logger, config, dest,
                                    terminate_event=terminate_event,
                                    interval=interval,
                                    oneshot=oneshot)
        self.url = self.config.server
        if "//" not in self.url:
            self.url = "//" + self.config.server
        parsed = urlparse.urlsplit(self.url, "https")
        if ":" not in parsed[1]:
            netloc = parsed[1] + ":8443"
        else:
            netloc = parsed[1]
        self.url = urlparse.urlunsplit((parsed[0], netloc, parsed[2], "", ""))

        if self.url[-1] != '/':
            self.url += '/'

        self.username = self.config.username
        self.password = self.config.password

        self.clusters_url = urlparse.urljoin(self.url, "api/clusters")
        self.hosts_url = urlparse.urljoin(self.url, "api/hosts")
        self.vms_url = urlparse.urljoin(self.url, "api/vms")

        self.auth = HTTPBasicAuth(self.config.username, self.config.password)

    def get(self, url):
        """
        Call RHEV-M server and retrieve what's on given url.
        """
        try:
            response = requests.get(url, auth=self.auth, verify=False)
            response.raise_for_status()
        except requests.RequestException as e:
            raise virt.VirtError("Unable to connect to RHEV-M server: %s" % str(e))
        # FIXME: other errors
        return response.text

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

        clusters_xml = self.get_xml(self.clusters_url)
        hosts_xml = self.get_xml(self.hosts_url)
        vms_xml = self.get_xml(self.vms_url)

        # Save ids of clusters that are "virt_service"
        for cluster in clusters_xml.findall('cluster'):
            cluster_id = cluster.get('id')
            virt_service = cluster.find('virt_service').text
            if virt_service.lower() == 'true':
                clusters.add(cluster_id)

        for host in hosts_xml.findall('host'):
            id = host.get('id')

            # Check if host is in cluster that is "virt_service"
            host_cluster = host.find('cluster')
            host_cluster_id = host_cluster.get('id')
            if host_cluster_id not in clusters:
                # Skip the host if it's cluster is not "virt_service"
                self.logger.debug('Cluster of host %s is not virt_service, skipped', id)
                continue

            if self.config.hypervisor_id == 'uuid':
                host_id = id
            elif self.config.hypervisor_id == 'hwuuid':
                try:
                    host_id = host.find('hardware_information').find('uuid').text
                except AttributeError:
                    self.logger.warn("Host %s doesn't have hardware uuid", id)
                    continue
            elif self.config.hypervisor_id == 'hostname':
                host_id = host.find('name').text
            else:
                raise virt.VirtError(
                    'Invalid option %s for hypervisor_id, use one of: uuid, hwuuid, or hostname' %
                    self.config.hypervisor_id)

            sockets = host.find('cpu').find('topology').get('sockets')
            if not sockets:
                sockets = host.find('cpu').find('topology').find('sockets').text

            facts = {
                virt.Hypervisor.CPU_SOCKET_FACT: sockets,
                virt.Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
            }
            try:
                version = host.find('version').get('full_version')
                if version:
                    facts[virt.Hypervisor.HYPERVISOR_VERSION_FACT] = version
            except AttributeError:
                pass

            hosts[id] = virt.Hypervisor(hypervisorId=host_id, name=host.find('name').text, facts=facts)
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

            hosts[host_id].guestIds.append(virt.Guest(guest_id, self, state))

        return {'hypervisors': hosts.values()}

    def ping(self):
        return True

if __name__ == '__main__':  # pragma: no cover
    # TODO: read from config
    if len(sys.argv) < 4:
        print("Usage: %s url username password" % sys.argv[0])
        sys.exit(0)

    import logging
    logger = logging.Logger("")
    config = Config('rhevm', 'rhevm', server=sys.argv[1], username=sys.argv[2],
                    password=sys.argv[3])
    rhevm = RhevM(logger, config)
    print dict((host, [guest.toDict() for guest in guests]) for host, guests in rhevm.getHostGuestMapping().items())
