# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Module for accessing vdsm, part of virt-who

Parts of this file is based on rhn-virtualization from spacewalk
https://github.com/spacewalkproject/spacewalk/tree/master/client/tools/rhn-virtualization

Copyright (C) 2011 Radek Novacek <rnovacek@redhat.com>

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
import re
from six.moves import xmlrpc_client
from six.moves.configparser import SafeConfigParser, NoSectionError, NoOptionError
import os
import subprocess
import ssl


from virtwho.virt import Virt, Guest
from virtwho.config import VirtConfigSection
from virtwho.virt.vdsm.jsonrpc import JsonRpcClient


class VdsmError(Exception):
    pass


VDSM_STATE_TO_GUEST_STATE = {
    'Down': Guest.STATE_SHUTOFF,
    'Migration Destination': Guest.STATE_SHUTOFF,
    'Migration Source': Guest.STATE_SHUTINGDOWN,
    'Paused': Guest.STATE_PAUSED,
    'Powering down': Guest.STATE_SHUTINGDOWN,
    'RebootInProgress': Guest.STATE_SHUTOFF,
    'Restoring state': Guest.STATE_SHUTOFF,
    'Saving State': Guest.STATE_SHUTOFF,
    'Up': Guest.STATE_RUNNING,
    'WaitForLaunch': Guest.STATE_SHUTOFF,
    'Powering up': Guest.STATE_SHUTOFF
}

VDSM_JSONRPC_TIMEOUT = 300  # 5 minutes, borrowed from esx MAX_WAIT_TIME


class VdsmConfigSection(VirtConfigSection):
    """
    This class is used for validation of vdsm virtualization backend
    section(s). It tries to validate options and combination of options that
    are specific for this virtualization backend. In specific, it attempts to read
    the given file and produces error messages if it is not usable.
    """
    VIRT_TYPE = 'vdsm'

    def __init__(self, section_name, wrapper, *args, **kwargs):
        super(VdsmConfigSection, self).__init__(section_name, wrapper, *args, **kwargs)


class Vdsm(Virt):
    """
    Class for interacting with vdsmd daemon.
    """
    CONFIG_TYPE = "vdsm"

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(Vdsm, self).__init__(logger, config, dest,
                                   terminate_event=terminate_event,
                                   interval=interval,
                                   oneshot=oneshot)
        self._read_config("/etc/vdsm/vdsm.conf")
        self.xmlrpc_client = None
        self.jsonrpc_client = None

    def isHypervisor(self):
        return False

    def _read_config(self, config_name):
        parser = SafeConfigParser()
        parser.read(config_name)
        try:
            self.ssl = parser.get("vars", "ssl").lower() in ["1", "true"]
        except (NoSectionError, NoOptionError):
            self.ssl = True

        if self.ssl:
            try:
                self.trust_store_path = parser.get("vars", "trust_store_path")
            except (NoSectionError, NoOptionError):
                self.trust_store_path = '/etc/pki/vdsm'
        else:
            self.trust_store_path = None
        try:
            self.management_port = parser.get("addresses", "management_port")
        except (NoSectionError, NoOptionError):
            self.management_port = '54321'

    def _get_local_vds_name(self, trusted_store_path):
        p = subprocess.Popen([
            '/usr/bin/openssl', 'x509', '-noout', '-subject', '-in',
            '%s/certs/vdsmcert.pem' % trusted_store_path], stdout=subprocess.PIPE, close_fds=True)
        out, err = p.communicate()
        if p.returncode != 0:
            return '0'
        return re.search('CN *= *([^,/$\n]+)', out.decode('UTF-8')).group(1)

    def _get_addr(self):
        return self._get_local_vds_name(self.trust_store_path)

    @staticmethod
    def _need_m2crypto():
        """Determine whether M2Crypto usage is necessary.

        If the python version supports SSL contexts and allows specifying them in xmlrpc clients, we do not need
        M2Crypto.
        """
        if 'RHSM_USE_M2CRYPTO' in os.environ and os.environ['RHSM_USE_M2CRYPTO'].lower() in ['true', '1', 'yes']:
            return False

        if not hasattr(ssl, 'create_default_context'):
            return False
        try:
            xmlrpc_client.ServerProxy('https://localhost', context=ssl.create_default_context())
            return True
        except TypeError:
            return False

    def _create_ssl_context(self):
        key_file = self.trust_store_path + '/keys/vdsmkey.pem'
        cert_file = self.trust_store_path + '/certs/vdsmcert.pem'
        ca_cert = self.trust_store_path + '/certs/cacert.pem'

        if self._need_m2crypto():
            ctx = ssl.create_default_context(capath=ca_cert)
            ctx.load_cert_chain(cert_file, key_file)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            from M2Crypto import SSL

            ctx = SSL.Context()

            ctx.set_verify(SSL.verify_peer | SSL.verify_fail_if_no_peer_cert, 16)
            ctx.load_verify_locations(ca_cert)
            ctx.load_cert(cert_file, key_file)
        return ctx

    def connect(self):
        if self.trust_store_path:
            ssl_context = self._create_ssl_context()
            addr = self._get_local_vds_name(self.trust_store_path)
            client = self._jsonrpc(addr, ssl_context) or self._xmlrpc(addr, ssl_context)
            if client:
                return

        # Try http versions if ssl is off or fails
        self._jsonrpc('localhost') or self._xmlrpc('localhost')

    def _jsonrpc(self, addr, ssl_context=None):
        try:
            jsonrpc_client = JsonRpcClient(addr, self.management_port, ssl_context, timeout=VDSM_JSONRPC_TIMEOUT)
            jsonrpc_client.connect()
            self.jsonrpc_client = jsonrpc_client
            return True
        except IOError:
            if ssl_context:
                description = 'JSON-RPC with SSL'
            else:
                description = 'JSON-RPC'
            self.logger.warning('Unable to connect via %s' % description, exc_info=True)
        return False

    def _xmlrpc(self, addr, ssl_context=None):
        try:
            transport = None
            if ssl_context:
                if self._need_m2crypto():
                    transport = xmlrpc_client.SafeTransport(context=ssl_context)
                else:
                    from M2Crypto.m2xmlrpclib import SSL_Transport
                    transport = SSL_Transport(ssl_context)
                uri = 'https://%s:%s' % (addr, self.management_port)
            else:
                uri = 'http://%s:%s' % (addr, self.management_port)
            xmlrpc_client_lib = xmlrpc_client.ServerProxy(uri, transport)
            xmlrpc_client_lib.system.listMethods()
            self.xmlrpc_client = xmlrpc_client_lib
            return True
        except Exception:  # NOTE: unfortunately there are many ways to fail, so the exception clause is broad
            if ssl_context:
                description = 'XML-RPC with SSL'
            else:
                description = 'XML-RPC'
            self.logger.warning('Unable to connect via %s' % description, exc_info=True)
        return False

    def prepare(self):
        self.connect()

    def _get_vm_list_xmlrpc(self):
        response = self.xmlrpc_client.list(True)
        if response['status']['code'] != 0:
            self.logger.error("Unable to list virtual machines: %s", response['status']['message'])
        else:
            return response['vmList']

    def _get_vm_list_jsonrpc(self):
        try:
            return self.jsonrpc_client.call('Host.getVMList', onlyUUID=False)
        except (IOError, RuntimeError):
            self.logger.exception("Unable to list virtual machines")

    def listDomains(self):
        domains = []
        vm_list = None
        if self.jsonrpc_client is not None:
            vm_list = self._get_vm_list_jsonrpc()
        elif self.xmlrpc_client is not None:
            vm_list = self._get_vm_list_xmlrpc()
        if vm_list:
            for vm in vm_list:
                status = VDSM_STATE_TO_GUEST_STATE.get(vm['status'], Guest.STATE_UNKNOWN)
                domains.append(Guest(vm['vmId'], self.CONFIG_TYPE, status))
        return domains
