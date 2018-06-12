# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Module for communication with libvirt, part of virt-who

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
from six.moves import urllib
from xml.etree import ElementTree

from virtwho.virt import (
    Hypervisor, Guest, VirtError, HostGuestAssociationReport,
    DomainListReport, Virt)
from virtwho.config import VirtConfigSection


class LibvirtdConfigSection(VirtConfigSection):
    """
    This class is used for validation of libvirtd virtualization backend
    section. It tries to validate options and combination of options that
    are specific for this virtualization backend.
    """

    VIRT_TYPE = 'libvirt'
    HYPERVISOR_ID = ('uuid', 'hostname')

    def __init__(self, section_name, wrapper, *args, **kwargs):
        super(LibvirtdConfigSection, self).__init__(section_name, wrapper, *args, **kwargs)
        # Note: no option is required for this virtualization backend. When no options
        # are specified, then virt-who will try to gather information from localhost

    def _validate_server(self, key):
        """
        Do validation of server option specific for this virtualization backend
        return: None or info-warning/error
        """
        # Server option is optional for libvirtd (libvirt hypervisor runs on the same
        # machine as virt-who)
        result = []
        if key not in self._values:
            self._values[key] = ''
        else:
            username = None
            url = self._values[key]
            if "//" not in url:
                url = "//" + url
            splitted_url = urllib.parse.urlsplit(url)

            hostname = splitted_url.hostname

            if hostname is None:
                hostname = ''

            if splitted_url.scheme:
                scheme = splitted_url.scheme
            else:
                result.append((
                    'info',
                    "Protocol is not specified in libvirt url, using qemu+ssh://"
                ))
                scheme = 'qemu+ssh'

            if 'username' in self._values:
                username = self._values['username']
            elif splitted_url.username:
                username = splitted_url.username

            if len(splitted_url.path) > 1:
                path = splitted_url.path
            else:
                result.append((
                    'info',
                    "Libvirt path is not specified in the url, using /system"
                ))
                path = '/system'

            self._values[key] = "%(scheme)s://%(username)s%(hostname)s%(path)s?no_tty=1" % {
                'username': ("%s@" % username) if username else '',
                'scheme': scheme,
                'hostname': hostname,
                'path': path
            }

        if len(result) == 0:
            return None
        else:
            return result

    def _validate_env(self, key):
        """
        Do validation of environment (env)
        :return: None or tuple with warning, when options are wrong
        """
        result = None
        sm_type = self._values['sm_type']
        if sm_type == 'sam' and 'server' in self._values and key not in self._values:
            result = (
                'error',
                "Option `%s` needs to be set in config: '%s'" % (key, self.name)
            )
        return result

    def _validate_owner(self, key):
        """
        Do validation of owner
        :return: None or tuple with warning, when options are wrong
        """
        result = None
        sm_type = self._values['sm_type']
        if sm_type == 'sam' and 'server' in self._values and key not in self._values:
            result = (
                'error',
                "Option `%s` needs to be set in config: '%s'" % (key, self.name)
            )
        return result

    def __validate_password(self, pass_key):
        """
        Validate password (encrypted or unecrypted) for libvirtd backend
        :return: None or warning/info, when options are wrong
        """
        result = None
        if pass_key not in self._values:
            return result
        else:
            if 'server' in self._values:
                server = self._values['server']
                if 'ssh://' in server or '://' not in server:
                    result = [(
                        'warn',
                        "Password authentication doesn't work with ssh transport on libvirt backend, "
                        "copy your public ssh key to the remote machine"
                    )]
            else:
                result = [(
                    'info',
                    "Options '%s' set in %s is useless for monitoring local libvirtd instance" %
                    (pass_key, self.name)
                )]
        return result

    def _validate_encrypted_password(self, pass_key):
        """
        Validate encrypted password
        :param pass_key: Key of encrypted password
        :return: None or tuple with warning, when options are wrong
        """
        if pass_key == 'encrypted_password':
            result = self.__validate_password(pass_key)
        else:
            result = super(LibvirtdConfigSection, self)._validate_encrypted_password(pass_key)
        return result

    def _validate_unencrypted_password(self, pass_key):
        """
        Validate unencrypted password
        :param pass_key: Key of unencrypted password
        :return: None or tuple with warning, when options are wrong
        """
        if pass_key == 'password':
            result = self.__validate_password(pass_key)
        else:
            result = super(LibvirtdConfigSection, self)._validate_unencrypted_password(pass_key)

        return result


class LibvirtdGuest(Guest):
    def __init__(self, domain):
        try:
            state = domain.state(0)[0]
        except AttributeError:
            # Some versions of libvirt doesn't have domain.state() method,
            # use first value from info instead
            state = domain.info()[0]

        super(LibvirtdGuest, self).__init__(
            uuid=domain.UUIDString(),
            virt_type=Libvirtd.CONFIG_TYPE,
            state=state)


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
            credential[4] = config.get('username', None)
        elif credential[0] == libvirt.VIR_CRED_PASSPHRASE:
            credential[4] = config.get('password', None)
        else:
            return -1
    return 0


class Libvirtd(Virt):
    """ Class for interacting with libvirt. """
    CONFIG_TYPE = "libvirt"

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False, registerEvents=True):
        super(Libvirtd, self).__init__(logger, config, dest,
                                       terminate_event=terminate_event,
                                       interval=interval,
                                       oneshot=oneshot)
        self.changedCallback = None
        self.registerEvents = registerEvents
        self._host_capabilities_xml = None
        self._host_socket_count = None
        self._host_uuid = None
        self._host_name = None
        self.eventLoopThread = None
        libvirt.registerErrorHandler(lambda ctx, error: None, None)

    def getVersion(self):
        """
        The constants used to extract the version numbers were found in
        /lib64/python2.7/site-packages/libvirt.py
        """
        version_num = self.virt.getVersion()
        major = version_num / 1000000
        version_num -= major * 1000000

        minor = version_num / 1000
        version_num -= minor * 1000

        release = version_num
        return "%(major)s.%(minor)s.%(release)s" % {
            'major': major,
            'minor': minor,
            'release': release
        }

    def getHypervisorType(self):
        return self.virt.getType()

    def isHypervisor(self):
        return bool(self.config.get('server', None))

    def _createEventLoop(self):
        libvirt.virEventRegisterDefaultImpl()
        if self.eventLoopThread is not None and self.eventLoopThread.isAlive():
            self.eventLoopThread.terminate()
        self.eventLoopThread = VirEventLoopThread(self.logger, name="libvirtEventLoop")
        self.eventLoopThread.setDaemon(True)
        self.eventLoopThread.start()

    def _connect(self):
        url = self.config.get('server', "")
        self.logger.info("Using libvirt url: %s", url if url else '""')
        try:
            if self.config.get('password', None):
                auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE], libvirt_cred_request, self.config]
                v = libvirt.openAuth(url, auth, libvirt.VIR_CONNECT_RO)
            else:
                v = libvirt.openReadOnly(url)
        except libvirt.libvirtError as e:
            self.logger.exception("Error in libvirt backend")
            raise VirtError(str(e))
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
        self.next_update = None

        while not self.is_terminated():
            if self.virt is None:
                self.virt = self._connect()

            if self.virt.isAlive() != 1:
                self._disconnect()
                self.virt = self._connect()

            if initial:
                report = self._get_report()
                self._send_data(report)
                initial = False
                self.next_update = time.time() + self.interval

            if self._oneshot:
                break

            time.sleep(1)
            if time.time() > self.next_update:
                report = self._get_report()
                self._send_data(report)
                self.next_update = time.time() + self.interval

        if self.eventLoopThread is not None and self.eventLoopThread.isAlive():
            self.eventLoopThread.terminate()
            self.eventLoopThread.join(1)
        self._disconnect()

    def _callback(self, *args, **kwargs):
        report = self._get_report()
        self._send_data(report)
        self.next_update = time.time() + self.interval

    def _get_report(self):
        if self.isHypervisor():
            return HostGuestAssociationReport(self.config, self._getHostGuestMapping())
        else:
            return DomainListReport(self.config, self._listDomains(), self._remote_host_id())

    def _lookupDomain(self, method, domain):
        '''
        Attempt to find the domain using given method.

        Returns None if the domain does not exist (it was probably just destroyed)
        '''
        try:
            return method(domain)
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                # Domain not found, most likely it was just destroyed
                return None
            else:
                # All other exceptions should be forwarded
                raise

    def _listDomains(self):
        domains = []
        try:
            # Active domains
            for domainID in self.virt.listDomainsID():
                domain = self._lookupDomain(self.virt.lookupByID, domainID)
                if domain is None:
                    # Domain not found, most likely it was just destroyed, ignoring
                    self.logger.debug("Lookup for domain by ID %s failed, probably it was just destroyed, ignoring" % domainID)
                    continue

                if domain.UUIDString() == "00000000-0000-0000-0000-000000000000":
                    # Don't send Domain-0 on xen (zeroed uuid)
                    continue
                domains.append(LibvirtdGuest(domain))

            # Non active domains
            for domainName in self.virt.listDefinedDomains():
                domain = self._lookupDomain(self.virt.lookupByName, domainName)
                if domain is None:
                    # Domain not found, most likely it was just destroyed, ignoring
                    self.logger.debug("Lookup for domain by name '%s' failed, probably it was just destroyed, ignoring" % domainName)
                    continue

                domains.append(LibvirtdGuest(domain))
        except libvirt.libvirtError as e:
            self.virt.close()
            raise VirtError(str(e))
        self.logger.debug("Libvirt domains found: %s", ", ".join(guest.uuid for guest in domains))
        return domains

    @property
    def host_capabilities_xml(self):
        if self._host_capabilities_xml is None:
            self._host_capabilities_xml = ElementTree.fromstring(self.virt.getCapabilities())
        return self._host_capabilities_xml

    def _remote_host_id(self):
        if self._host_uuid is None and 'hypervisor_id' in self.config:
            if self.config['hypervisor_id'] == 'uuid':
                self._host_uuid = self.host_capabilities_xml.find('host/uuid').text
            elif self.config['hypervisor_id'] == 'hostname':
                self._host_uuid = self.virt.getHostname()
        return self._host_uuid

    def _remote_host_name(self):
        if self._host_name is None:
            try:
                self._host_name = self.host_capabilities_xml.find('host/name').text
            except AttributeError:
                self._host_name = None
        return self._host_name

    def _remote_host_sockets(self):
        if self._host_socket_count is None:
            try:
                self._host_socket_count = self.host_capabilities_xml.find('host/cpu/topology').get('sockets')
            except AttributeError:
                self._host_socket_count = None
        return self._host_socket_count

    def _getHostGuestMapping(self):
        mapping = {'hypervisors': []}
        facts = {
            Hypervisor.CPU_SOCKET_FACT: self._remote_host_sockets(),
            Hypervisor.HYPERVISOR_TYPE_FACT: self.virt.getType(),
            Hypervisor.HYPERVISOR_VERSION_FACT: self.virt.getVersion(),
            Hypervisor.SYSTEM_UUID_FACT: self.host_capabilities_xml.find('host/uuid').text,
        }
        host = Hypervisor(hypervisorId=self._remote_host_id(),
                          guestIds=self._listDomains(),
                          name=self._remote_host_name(),
                          facts=facts)
        mapping['hypervisors'].append(host)
        return mapping
