"""
Module for accessing vdsm, part of virt-who

Parts of this file is based on rhn-virtualization from spacewalk
http://git.fedorahosted.org/git/?p=spacewalk.git;a=tree;f=client/tools/rhn-virtualization

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

import xmlrpclib
from ConfigParser import SafeConfigParser, NoSectionError
import subprocess

class VdsmError(Exception):
    pass

class Domain:
    """ Class for compatibility with libvirt Domain class. Only UUID supported. """
    def __init__(self, uuid):
        self.uuid = uuid

    def UUIDString(self):
        return self.uuid

    def __str__(self):
        return self.uuid

class VDSM:
    def __init__(self, logger):
        self.logger = logger
        self._readConfig("/etc/vdsm/vdsm.conf")
        self.connect()

    def _readConfig(self, configName):
        parser = SafeConfigParser()
        parser.read(configName)
        try:
            self.ssl = parser.get("vars", "ssl").lower() in ["1", "true"]
            if self.ssl:
                self.trust_store_path = parser.get("vars", "trust_store_path")
            else:
                self.trust_store_path = None
            self.management_port = parser.get("addresses", "management_port")
        except NoSectionError, e:
            raise VdsmError("Error in vdsm configuration file: %s" % str(e))

    def _getLocalVdsName(self, tsPath):
        p = subprocess.Popen(['/usr/bin/openssl', 'x509', '-noout', '-subject', '-in',
                '%s/certs/vdsmcert.pem' % tsPath], stdout=subprocess.PIPE, close_fds=True)
        out, err = p.communicate()
        if p.returncode != 0:
            return '0'
        return out.split('=')[-1].strip()

    def _secureConnect(self):
        addr = self._getLocalVdsName(self.trust_store_path)

        from M2Crypto.m2xmlrpclib import SSL_Transport
        from M2Crypto import SSL

        KEYFILE = self.trust_store_path + '/keys/vdsmkey.pem'
        CERTFILE = self.trust_store_path + '/certs/vdsmcert.pem'
        CACERT = self.trust_store_path + '/certs/cacert.pem'

        ctx = SSL.Context('sslv3')

        ctx.set_verify(SSL.verify_peer | SSL.verify_fail_if_no_peer_cert, 16)
        ctx.load_verify_locations(CACERT)
        ctx.load_cert(CERTFILE, KEYFILE)

        return xmlrpclib.Server('https://%s:%s' % (addr, self.management_port), SSL_Transport(ctx))

    def connect(self):
        if self.trust_store_path:
            try:
                self.server = self._secureConnect()
                return
            except Exception, e:
                self.logger.exception(e)
        # Try http version if ssl is off or fails
        self.server = xmlrpclib.Server("http://localhost:%s" % self.management_port)

    def listDomains(self):
        domains = []
        response = self.server.list(True)
        if response['status']['code'] != 0:
            self.logger.error("Unable to list virtual machines: %s" % response['status']['message'])
        else:
            for vm in response['vmList']:
                domains.append(Domain(vm['vmId']))
        return domains

    def ping(self):
        # Not implemented yet
        return True

if __name__ == '__main__':
    import logging
    logger = logging.getLogger("rhsm-app." + __name__)
    vdsm = VDSM(logger)
    print vdsm.listDomains()
