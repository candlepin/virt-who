"""
Agent for reporting virtual guest IDs to subscription-manager

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

import sys
import os

import libvirt

import rhsm.connection as rhsm_connection
import rhsm.certificate as rhsm_certificate
import rhsm.config as rhsm_config

import logging
import log

from optparse import OptionParser


class Virt:
    """ Class for interacting with libvirt. """
    def __init__(self):
        self.virt = libvirt.openReadOnly("")

    def listDomains(self):
        """ Get list of all domains. """
        domains = []

        # Active domains
        for domainID in self.virt.listDomainsID():
            domain = self.virt.lookupByID(domainID)
            domains.append(domain)
            logger.debug("Virtual machine found: %s: %s" % (domain.name(), domain.UUIDString()))

        # Non active domains
        for domainName in self.virt.listDefinedDomains():
            domain = self.virt.lookupByName(domainName)
            domains.append(domain)
            logger.debug("Virtual machine found: %s: %s" % (domainName, domain.UUIDString()))

        return domains

    def __del__(self):
        self.virt.close()


class RHSM:
    """ Class for interacting subscription-manager. """
    def __init__(self):
        self.cert_uuid = None

        self.readConfig()

        # Consumer ID obtained from consumer certificate
        self.cert_uuid = self.uuid()

    def readConfig(self):
        """ Parse rhsm.conf in order to obtain consumer
            certificate and key paths. """
        self.config = rhsm_config.initConfig()
        consumerCertDir = self.config.get("rhsm", "consumerCertDir")
        cert = 'cert.pem'
        key = 'key.pem'
        self.cert_file = os.path.join(consumerCertDir, cert)
        self.key_file = os.path.join(consumerCertDir, key)
        if not os.access(self.cert_file, os.R_OK):
            logger.error("Unable to read certificate, system is not registered or you are not root")
            sys.exit(1)

    def connect(self):
        """ Connect to the subscription-manager. """
        self.connection = rhsm_connection.UEPConnection(
                cert_file=self.cert_file, key_file=self.key_file)
        if not self.connection.ping()['result']:
            logger.error("Unable to connect to the server")

    def sendVirtGuests(self, domains):
        """ Update consumer facts with UUIDs of virtual guests. """
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
            logger.debug("No need to update facts (%s)" % facts["virt.guests"])
            return

        # Update consumer facts
        logger.debug("Sending updates virt.guests facts: %s" % uuids_string)
        facts["virt.guests"] = uuids_string

        # Send it to the server
        self.connection.updateConsumerFacts(self.uuid(), facts)

    def uuid(self):
        """ Read consumer certificate and get consumer UUID from it. """
        if not self.cert_uuid:
            try:
                f = open(self.cert_file, "r")
            except Exception as e:
                logger.error("Unable to open certificate (%s): %s" % (self.cert_file, e.message))
                return ""
            certificate = rhsm_certificate.Certificate(f.read())
            f.close()
            self.cert_uuid = certificate.subject().get('CN')
        return self.cert_uuid

    def getFacts(self):
        """ Get fact for current consumer. """
        self.consumer = self.connection.conn.request_get('/consumers/%s' % self.uuid())
        return self.consumer['facts']

if __name__ == '__main__':
    log.init_logger()

    logger = logging.getLogger("rhsm-app." + __name__)

    parser = OptionParser(description="Agent for reporting virtual guest IDs to subscription-manager")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")

    (options, args) = parser.parse_args()

    if options.debug:
        logger.setLevel(logging.DEBUG)

    # Log libvirt errors
    libvirt.registerErrorHandler(lambda ctx, error: logger.debug(error), None)

    virt = Virt()
    rhsm = RHSM()
    rhsm.connect()

    rhsm.sendVirtGuests(virt.listDomains())
