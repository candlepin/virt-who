"""
Module for communcating with RHEV-M, part of virt-who

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
import urllib2
import base64

import virt

from config import Config

# Import XML parser
try:
    from elementtree import ElementTree
except ImportError:
    from xml.etree import ElementTree


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

    def __init__(self, logger, config):
        super(RhevM, self).__init__(logger, config)
        self.url = self.config.server
        if "//" not in self.url:
            self.url = "//" + self.config.server
        parsed = urlparse.urlsplit(self.url, "https")
        if ":" not in parsed[1]:
            netloc = parsed[1] + ":8443"
        else:
            netloc = parsed[1]
        self.url = urlparse.urlunsplit((parsed[0], netloc, parsed[2], "", ""))

        self.username = self.config.username
        self.password = self.config.password

        self.clusters_url = urlparse.urljoin(self.url, "/api/clusters")
        self.hosts_url = urlparse.urljoin(self.url, "/api/hosts")
        self.vms_url = urlparse.urljoin(self.url, "/api/vms")

        self.auth = base64.encodestring('%s:%s' % (self.config.username, self.config.password))[:-1]

    def get(self, url):
        """
        Call RHEV-M server and retrieve what's on given url.
        """
        request = urllib2.Request(url)
        request.add_header("Authorization", "Basic %s" % self.auth)
        return urllib2.urlopen(request)

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

        clusters_xml = ElementTree.parse(self.get(self.clusters_url))
        hosts_xml = ElementTree.parse(self.get(self.hosts_url))
        vms_xml = ElementTree.parse(self.get(self.vms_url))

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
                hosts[id] = virt.Hypervisor(id)
            elif self.config.hypervisor_id == 'hwuuid':
                try:
                    hosts[id] = virt.Hypervisor(
                        host.find('hardware_information').find('uuid').text
                    )
                except AttributeError:
                    self.logger.warn("Host %s doesn't have hardware uuid", id)
                    continue
            elif self.config.hypervisor_id == 'hostname':
                hosts[id] = virt.Hypervisor(host.find('name').text)
            else:
                raise virt.VirtError(
                    'Reporting of hypervisor %s is not implemented in %s backend',
                    self.config.hypervisor_id, self.CONFIG_TYPE)
            mapping[id] = []
            # BZ 1065465 Add hostname to hypervisor profile
            hosts[id].name = host.find('name').text
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
                state = RHEVM_STATE_TO_GUEST_STATE.get(
                    vm.find('status').find('state').text.lower(),
                    virt.Guest.STATE_UNKNOWN)
            except AttributeError:
                self.logger.warning(
                    "Guest %s doesn't report any status",
                    guest_id)
                state = virt.Guest.STATE_UNKNOWN

            hosts[host_id].guestIds.append(virt.Guest(guest_id, self, state))

        return {'hypervisors': [h for id, h in hosts.items]}

    def ping(self):
        return True

if __name__ == '__main__':
    # TODO: read from config
    if len(sys.argv) < 4:
        print("Usage: %s url username password" % sys.argv[0])
        sys.exit(0)

    import logging
    logger = logging.Logger("")
    config = Config('rhevm', 'rhevm', sys.argv[1], sys.argv[2], sys.argv[3])
    rhevm = RhevM(logger, config)
    print dict((host, [guest.toDict() for guest in guests]) for host, guests in rhevm.getHostGuestMapping().items())
