"""
Module for communcating with subscription-manager, part of virt-who

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

import os

import rhsm.connection as rhsm_connection
import rhsm.certificate as rhsm_certificate
import rhsm.config as rhsm_config

from ..manager import Manager


class SubscriptionManagerError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class SubscriptionManager(Manager):
    smType = "sam"

    """ Class for interacting subscription-manager. """
    def __init__(self, logger, options):
        self.logger = logger
        self.options = options
        self.cert_uuid = None

        self.config = rhsm_config.initConfig(rhsm_config.DEFAULT_CONFIG_PATH)
        self.readConfig()

        # Consumer ID obtained from consumer certificate
        self.cert_uuid = self.uuid()

    def readConfig(self):
        """ Parse rhsm.conf in order to obtain consumer
            certificate and key paths. """
        consumerCertDir = self.config.get("rhsm", "consumerCertDir")
        cert = 'cert.pem'
        key = 'key.pem'
        self.cert_file = os.path.join(consumerCertDir, cert)
        self.key_file = os.path.join(consumerCertDir, key)
        if not os.access(self.cert_file, os.R_OK):
            raise SubscriptionManagerError("Unable to read certificate, system is not registered or you are not root")

    def _connect(self):
        """ Connect to the subscription-manager. """
        self.connection = rhsm_connection.UEPConnection(
            host=self.config.get('server', 'hostname'),
            ssl_port=int(self.config.get('server', 'port')),
            handler=self.config.get('server', 'prefix'),
            proxy_hostname=self.config.get('server', 'proxy_hostname'),
            proxy_port=self.config.get('server', 'proxy_port'),
            proxy_user=self.config.get('server', 'proxy_user'),
            proxy_password=self.config.get('server', 'proxy_password'),
            cert_file=self.cert_file, key_file=self.key_file)
        if not self.connection.ping()['result']:
            raise SubscriptionManagerError("Unable to obtain status from server, UEPConnection is likely not usable.")

    def sendVirtGuests(self, domains):
        """
        Update consumer facts with info about virtual guests.

        :param domain: List of guest UUIDs for current machine or list of
            dictionaries in the format: [
                {
                    'guestId': <uuid of guest>,
                    'attributes': { # supplemental list a attributes, supported are following:
                        'hypervisorType': <type of hypervisor, e.g. QEMU>,
                        'virtWhoType': <virtwho type of operation, e.g. libvirt>,
                        'active': <1 if guest is active, 0 otherwise, -1 on error>
                    },
                },
                ...
            ]
        :type domain: list of str or list of dict domains
        """

        self._connect()

        # Sort the list
        key = None
        if len(domains) > 0:
            if isinstance(domains[0], basestring):
                key = "guestId"
            domains.sort(key=key)

        if key is not None:
            self.logger.info("Sending list of uuids: %s" % [domain[key] for domain in domains])
        else:
            self.logger.info("Sending list of uuids: %s" % domains)

        # Send list of guest uuids to the server
        self.connection.updateConsumer(self.uuid(), guest_uuids=domains)

    def hypervisorCheckIn(self, config, mapping, type=None):
        """ Send hosts to guests mapping to subscription manager. """
        self.logger.info("Sending update in hosts-to-guests mapping: %s" % mapping)

        self._connect()

        # Send the mapping
        return self.connection.hypervisorCheckIn(config.owner, config.env, mapping)

    def uuid(self):
        """ Read consumer certificate and get consumer UUID from it. """
        if not self.cert_uuid:
            try:
                certificate = rhsm_certificate.create_from_file(self.cert_file)
                self.cert_uuid = certificate.subject["CN"]
            except Exception, e:
                raise SubscriptionManagerError("Unable to open certificate %s (%s):" % (self.cert_file, str(e)))
        return self.cert_uuid

    def getFacts(self):
        """ Get fact for current consumer. """
        self.consumer = self.connection.conn.request_get('/consumers/%s' % self.uuid())
        return self.consumer['facts']
