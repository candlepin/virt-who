"""
Module for communcating with libvirt, part of virt-who

Copyright (C) 2014 Radek Novacek <rnovacek@redhat.com>

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

import time
import libvirt
import threading
import urlparse

import virt

# Import XML parser
try:
    from elementtree import ElementTree
except ImportError:
    from xml.etree import ElementTree


class LibvirtdGuest(virt.Guest):
    def __init__(self, libvirtd, domain):
        try:
            state = domain.state(0)[0]
        except AttributeError:
            # Some versions of libvirt doesn't have domain.state() method,
            # use first value from info instead
            state = domain.info()[0]

        super(LibvirtdGuest, self).__init__(
            uuid=domain.UUIDString(),
            virt=libvirtd,
            state=state,
            hypervisorType=libvirtd.virt.getType())


class VirEventLoopThread(threading.Thread):
    def __init__(self, logger, *args, **kwargs):
        self._terminated = threading.Event()
        threading.Thread.__init__(self, *args, **kwargs)

    def run(self):
        while not self._terminated.is_set():
            libvirt.virEventRunDefaultImpl()

    def terminate(self):
        self._terminated.set()


def libvirt_cred_request(credentials, config):
    """ Callback function for requesting credentials from libvirt """
    for credential in credentials:
        if credential[0] == libvirt.VIR_CRED_AUTHNAME:
            credential[4] = config.username
        elif credential[0] == libvirt.VIR_CRED_PASSPHRASE:
            credential[4] = config.password
        else:
            return -1
    return 0


class Libvirtd(virt.Virt):
    """ Class for interacting with libvirt. """
    CONFIG_TYPE = "libvirt"

    def __init__(self, logger, config, registerEvents=True):
        super(Libvirtd, self).__init__(logger, config)
        self.changedCallback = None
        self.registerEvents = registerEvents
        self._host_uuid = None
        self._host_name = None
        self.eventLoopThread = None
        libvirt.registerErrorHandler(lambda ctx, error: None, None)

    def isHypervisor(self):
        return bool(self.config.server)

    def _get_url(self):
        if self.config.server:
            scheme = username = netloc = path = None
            url = self.config.server
            if "//" not in url:
                url = "//" + url
            splitted_url = urlparse.urlsplit(url)

            netloc = splitted_url.netloc

            if splitted_url.scheme:
                scheme = splitted_url.scheme
            else:
                self.logger.info("Protocol is not specified in libvirt url, using qemu+ssh://")
                scheme = 'qemu+ssh'

            if self.config.username:
                username = self.config.username
            elif splitted_url.username:
                username = splitted_url.username

            if len(splitted_url.path) > 1:
                path = splitted_url.path
            else:
                self.logger.info("Libvirt path is not specified in the url, using /system")
                path = '/system'

            return "%(scheme)s://%(username)s%(netloc)s%(path)s?no_tty=1" % {
                'username': ("%s@" % username) if username else '',
                'scheme': scheme,
                'netloc': netloc,
                'path': path
            }
        return ''

    def _createEventLoop(self):
        libvirt.virEventRegisterDefaultImpl()
        if self.eventLoopThread is not None and self.eventLoopThread.isAlive():
            self.eventLoopThread.terminate()
        self.eventLoopThread = VirEventLoopThread(self.logger, name="libvirtEventLoop")
        self.eventLoopThread.setDaemon(True)
        self.eventLoopThread.start()

    def _connect(self):
        url = self._get_url()
        self.logger.info("Using libvirt url: %s", url if url else '""')
        try:
            if self.config.password:
                auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE], libvirt_cred_request, self.config]
                v = libvirt.openAuth(url, auth, libvirt.VIR_CONNECT_RO)
            else:
                v = libvirt.openReadOnly(url)
        except libvirt.libvirtError as e:
            self.logger.exception("Error in libvirt backend")
            raise virt.VirtError(str(e))
        v.domainEventRegister(self._callback, None)
        v.setKeepAlive(5, 3)
        return v

    def _disconnect(self):
        if self.virt is None:
            return
        try:
            self.virt.domainEventDeregister(self._callback)
            self.virt.close()
        except libvirt.libvirtError:
            pass
        self.virt = None

    def _run(self):
        self._createEventLoop()

        self.virt = None
        initial = True

        while not self.is_terminated():
            if self.virt is None:
                self.virt = self._connect()

            if self.virt.isAlive() != 1:
                self._disconnect()
                self.virt = self._connect()

            if initial:
                report = self._get_report()
                self._queue.put(report)
                initial = False

            time.sleep(1)
        self._disconnect()

    def _callback(self, *args, **kwargs):
        report = self._get_report()
        self._queue.put(report)

    def _get_report(self):
        if self.isHypervisor():
            return virt.HostGuestAssociationReport(self.config, self._getHostGuestMapping())
        else:
            return virt.DomainListReport(self.config, self._listDomains())

    def _listDomains(self):
        domains = []
        try:
            # Active domains
            for domainID in self.virt.listDomainsID():
                domain = self.virt.lookupByID(domainID)
                if domain.UUIDString() == "00000000-0000-0000-0000-000000000000":
                    # Don't send Domain-0 on xen (zeroed uuid)
                    continue
                domains.append(LibvirtdGuest(self, domain))
                self.logger.debug("Virtual machine found: %s: %s" % (domain.name(), domain.UUIDString()))

            # Non active domains
            for domainName in self.virt.listDefinedDomains():
                domain = self.virt.lookupByName(domainName)
                domains.append(LibvirtdGuest(self, domain))
                self.logger.debug("Virtual machine found: %s: %s" % (domainName, domain.UUIDString()))
        except libvirt.libvirtError as e:
            self.virt.close()
            raise virt.VirtError(str(e))
        self.logger.debug("Libvirt domains found: %s" % [guest.uuid for guest in domains])
        return domains

    def _remote_host_id(self):
        if self._host_uuid is None:
            if self.config.hypervisor_id == 'uuid':
                xml = ElementTree.fromstring(self.virt.getCapabilities())
                self._host_uuid = xml.find('host/uuid').text
            elif self.config.hypervisor_id == 'hostname':
                self._host_uuid = self.virt.getHostname()
            else:
                raise virt.VirtError('Reporting of hypervisor %s is not implemented in %s backend' %
                                     (self.config.hypervisor_id, self.CONFIG_TYPE))
        return self._host_uuid

    def _remote_host_name(self):
        if self._host_name is None:
            xml = ElementTree.fromstring(self.virt.getCapabilities())
            if (xml.find('host/name') is not None):
                self._host_name = xml.find('host/name').text
        return self._host_name

    def _getHostGuestMapping(self):
        mapping = {'hypervisors': []}
        host = virt.Hypervisor(hypervisorId=self._remote_host_id(),
                               guestIds=self._listDomains(),
                               name=self._remote_host_name())
        mapping['hypervisors'].append(host)
        return mapping
