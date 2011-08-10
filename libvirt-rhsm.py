#!/usr/bin/python
#
# Agent for reporting virtual guest IDs to subscription-manager
#
# Copyright (C) 2011 Radek Novacek <rnovacek@redhat.com>

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


import sys
import os

import libvirt

import rhsm.connection as rhsm_connection
import rhsm.certificate as rhsm_certificate
import rhsm.config as rhsm_config

import logging


# TODO: proper parameter handling
if "-d" in sys.argv or "--debug" in sys.argv:
    import log
    log.init_logger()
    log = logging.getLogger('rhsm-app.' + __name__)
else:
    log = logging.getLogger()

# Log libvirt errors
def f(ctx, error):
    log.debug(error)
libvirt.registerErrorHandler(f, None)


class Virt:
    def listDomains(self):
        domains = []
        virt = libvirt.openReadOnly("")

        # Active domains
        for domainID in virt.listDomainsID():
            domain = virt.lookupByID(domainID)
            domains.append(domain)
            log.debug("Virtual machine found: %s: %s" % (domain.name(), domain.UUIDString()))

        # Non active domains
        for domainName in virt.listDefinedDomains():
            domain = virt.lookupByName(domainName)
            domains.append(domain)
            log.debug("Virtual machine found: %s: %s" % (domainName, domain.UUIDString()))

        virt.close()
        return domains


class RHSM:
    cert_uuid = None # Consumer ID obtained from consumer certificate

    def readConfig(self):
        """ Parse rhsm.conf in order to obtain consumer certificate and key paths. """
        self.config = rhsm_config.initConfig()
        consumerCertDir = self.config.get("rhsm", "consumerCertDir")
        cert = 'cert.pem'
        key = 'key.pem'
        self.cert_file = os.path.join(consumerCertDir, cert)
        self.key_file = os.path.join(consumerCertDir, key)

    def connect(self):
        self.readConfig()
        self.connection = rhsm_connection.UEPConnection(cert_file=self.cert_file, key_file=self.key_file)
        if not self.connection.ping()['result']:
            log.error("Unable to connect to the server")

    def sendVirtGuests(self, domains):
        # Get consumer facts from server
        facts = self.getFacts()

        # Get comma separated list of UUIDs
        uuids = []
        for domain in domains:
            uuids.append(domain.UUIDString())
        uuids_string = ",".join(uuids)

        # Check if facts differ
        if "virt.guests" in facts and facts["virt.guests"] == uuids_string:
            # There are the same, no need to update them
            log.debug("No need to update facts (%s)" % facts["virt.guests"])
            return

        # Update consumer facts
        log.debug("Sending updates virt.guests facts: %s" % uuids_string)
        facts["virt.guests"] = uuids_string

        # Send it to the server
        self.connection.updateConsumerFacts(self.uuid(), facts)

    def uuid(self):
        if not self.cert_uuid:
            try:
                f = open(self.cert_file, "r")
            except Exception as e:
                log.error("Unable to open certificate (%s): %s" % (self.cert_file, e.message))
                return ""
            certificate = rhsm_certificate.Certificate(f.read())
            f.close()
            self.cert_uuid = certificate.subject().get('CN')
        return self.cert_uuid

    def getFacts(self):
        self.consumer = self.connection.conn.request_get('/consumers/%s' % self.uuid())
        return self.consumer['facts']

if __name__ == '__main__':
    virt = Virt()
    rhsm = RHSM()
    rhsm.connect()

    rhsm.sendVirtGuests(virt.listDomains())
