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
import xmlrpclib
from ConfigParser import SafeConfigParser, NoSectionError, NoOptionError
import subprocess

from virtwho.virt import Virt, Guest


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


class Vdsm(Virt):
    CONFIG_TYPE = "vdsm"

    def __init__(self, logger, config, shared_data, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(Vdsm, self).__init__(logger, config, shared_data, dest,
                                   terminate_event=terminate_event,
                                   interval=interval,
                                   oneshot=oneshot)
        self._readConfig("/etc/vdsm/vdsm.conf")

    def isHypervisor(self):
        return False

    def _readConfig(self, configName):
        parser = SafeConfigParser()
        parser.read(configName)
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

    def _getLocalVdsName(self, tsPath):
        p = subprocess.Popen([
            '/usr/bin/openssl', 'x509', '-noout', '-subject', '-in',
            '%s/certs/vdsmcert.pem' % tsPath], stdout=subprocess.PIPE, close_fds=True)
        out, err = p.communicate()
        if p.returncode != 0:
            return '0'
        return re.search('/CN=([^/$\n]+)', out).group(1)

    def _secureConnect(self):
        addr = self._getLocalVdsName(self.trust_store_path)

        from M2Crypto.m2xmlrpclib import SSL_Transport
        from M2Crypto import SSL

        KEYFILE = self.trust_store_path + '/keys/vdsmkey.pem'
        CERTFILE = self.trust_store_path + '/certs/vdsmcert.pem'
        CACERT = self.trust_store_path + '/certs/cacert.pem'

        ctx = SSL.Context()

        ctx.set_verify(SSL.verify_peer | SSL.verify_fail_if_no_peer_cert, 16)
        ctx.load_verify_locations(CACERT)
        ctx.load_cert(CERTFILE, KEYFILE)

        return xmlrpclib.Server('https://%s:%s' % (addr, self.management_port), SSL_Transport(ctx))

    def connect(self):
        if self.trust_store_path:
            try:
                self.server = self._secureConnect()
                return
            except Exception as e:
                self.logger.exception(e)
        # Try http version if ssl is off or fails
        self.server = xmlrpclib.Server("http://localhost:%s" % self.management_port)

    def prepare(self):
        self.connect()

    def listDomains(self):
        domains = []
        response = self.server.list(True)
        if response['status']['code'] != 0:
            self.logger.error("Unable to list virtual machines: %s", response['status']['message'])
        else:
            for vm in response['vmList']:
                status = VDSM_STATE_TO_GUEST_STATE.get(vm['status'], Guest.STATE_UNKNOWN)
                domains.append(Guest(vm['vmId'], self, status))
        return domains


if __name__ == '__main__':  # pragma: no cover
    import logging
    logger = logging.getLogger("virtwho.vdsm.main")
    logger.addHandler(logging.StreamHandler())
    vdsm = Vdsm(logger, None)
    print vdsm.listDomains()
