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
import json
from httplib import BadStatusLine

import rhsm.connection as rhsm_connection
import rhsm.certificate as rhsm_certificate
import rhsm.config as rhsm_config

from virtwho.manager import Manager, ManagerError, ManagerFatalError, ManagerThrottleError
from virtwho.virt import AbstractVirtReport


class SubscriptionManagerError(ManagerError):
    pass


class SubscriptionManagerUnregisteredError(ManagerFatalError):
    pass


# Mapping between strings returned from getJob and report statuses
STATE_MAPPING = {
    'FINISHED': AbstractVirtReport.STATE_FINISHED,
    'CANCELED': AbstractVirtReport.STATE_CANCELED,
    'FAILED': AbstractVirtReport.STATE_FAILED,
    'RUNNING': AbstractVirtReport.STATE_PROCESSING,
}


class SubscriptionManager(Manager):
    smType = "sam"

    """ Class for interacting subscription-manager. """
    def __init__(self, logger, options):
        self.logger = logger
        self.options = options
        self.cert_uuid = None

        self.rhsm_config = rhsm_config.initConfig(rhsm_config.DEFAULT_CONFIG_PATH)
        self.readConfig()

    def readConfig(self):
        """ Parse rhsm.conf in order to obtain consumer
            certificate and key paths. """
        consumerCertDir = self.rhsm_config.get("rhsm", "consumerCertDir")
        cert = 'cert.pem'
        key = 'key.pem'
        self.cert_file = os.path.join(consumerCertDir, cert)
        self.key_file = os.path.join(consumerCertDir, key)

    def _connect(self, config=None):
        """ Connect to the subscription-manager. """

        kwargs = {
            'host': self.rhsm_config.get('server', 'hostname'),
            'ssl_port': int(self.rhsm_config.get('server', 'port')),
            'handler': self.rhsm_config.get('server', 'prefix'),
            'proxy_hostname': self.rhsm_config.get('server', 'proxy_hostname'),
            'proxy_port': self.rhsm_config.get('server', 'proxy_port'),
            'proxy_user': self.rhsm_config.get('server', 'proxy_user'),
            'proxy_password': self.rhsm_config.get('server', 'proxy_password'),
            'insecure': self.rhsm_config.get('server', 'insecure')
        }

        rhsm_username = None
        rhsm_password = None

        if config:
            rhsm_username = config.rhsm_username
            rhsm_password = config.rhsm_password

            # Testing for None is necessary, it might be an empty string

            if config.rhsm_hostname is not None:
                kwargs['host'] = config.rhsm_hostname

            if config.rhsm_port is not None:
                kwargs['ssl_port'] = int(config.rhsm_port)

            if config.rhsm_prefix is not None:
                kwargs['handler'] = config.rhsm_prefix

            if config.rhsm_proxy_hostname is not None:
                kwargs['proxy_hostname'] = config.rhsm_proxy_hostname

            if config.rhsm_proxy_port is not None:
                kwargs['proxy_port'] = config.rhsm_proxy_port

            if config.rhsm_proxy_user is not None:
                kwargs['proxy_user'] = config.rhsm_proxy_user

            if config.rhsm_proxy_password is not None:
                kwargs['proxy_password'] = config.rhsm_proxy_password

            if config.rhsm_insecure is not None:
                kwargs['insecure'] = config.rhsm_insecure

        if rhsm_username and rhsm_password:
            self.logger.debug("Authenticating with RHSM username %s", rhsm_username)
            kwargs['username'] = rhsm_username
            kwargs['password'] = rhsm_password
        else:
            self.logger.debug("Authenticating with certificate: %s", self.cert_file)
            if not os.access(self.cert_file, os.R_OK):
                raise SubscriptionManagerUnregisteredError(
                    "Unable to read certificate, system is not registered or you are not root")
            kwargs['cert_file'] = self.cert_file
            kwargs['key_file'] = self.key_file

        self.connection = rhsm_connection.UEPConnection(**kwargs)
        try:
            if not self.connection.ping()['result']:
                raise SubscriptionManagerError("Unable to obtain status from server, UEPConnection is likely not usable.")
        except BadStatusLine:
            raise ManagerError("Communication with subscription manager interrupted")

    def sendVirtGuests(self, report, options=None):
        """
        Update consumer facts with info about virtual guests.

        `guests` is a list of `Guest` instances (or it children).
        """
        guests = report.guests
        self._connect()

        # Sort the list
        guests.sort(key=lambda item: item.uuid)

        serialized_guests = [guest.toDict() for guest in guests]
        self.logger.info('Sending update in guests lists for config '
                         '"%s": %d guests found',
                         report.config.name, len(guests))
        self.logger.debug("Domain info: %s", json.dumps(serialized_guests, indent=4))

        # Send list of guest uuids to the server
        try:
            self.connection.updateConsumer(self.uuid(), guest_uuids=serialized_guests, hypervisor_id=report.hypervisor_id)
        except rhsm_connection.GoneException:
            raise ManagerError("Communication with subscription manager failed: consumer no longer exists")
        except rhsm_connection.RateLimitExceededException as e:
            retry_after = int(getattr(e, 'headers', {}).get('Retry-After', '60'))
            raise ManagerThrottleError(retry_after)
        report.state = AbstractVirtReport.STATE_FINISHED

    def hypervisorCheckIn(self, report, options=None):
        """ Send hosts to guests mapping to subscription manager. """
        mapping = report.association
        serialized_mapping = {}

        self._connect(report.config)
        self.logger.debug("Checking if server has capability 'hypervisor_async'")
        is_async = hasattr(self.connection, 'has_capability') and self.connection.has_capability('hypervisors_async')
        if is_async and os.environ.get('VIRTWHO_DISABLE_ASYNC', '').lower() in ['1', 'yes', 'true']:
            self.logger.info("Async reports are supported but explicitly disabled")
            is_async = False

        if is_async:
            self.logger.debug("Server has capability 'hypervisors_async'")
            # Transform the mapping into the async version
            serialized_mapping = {'hypervisors': [h.toDict() for h in mapping['hypervisors']]}

        else:
            self.logger.debug("Server does not have 'hypervisors_async' capability")
            # Reformat the data from the mapping to make it fit with
            # the old api.
            for hypervisor in mapping['hypervisors']:
                guests = [g.toDict() for g in hypervisor.guestIds]
                serialized_mapping[hypervisor.hypervisorId] = guests

        hypervisor_count = len(mapping['hypervisors'])
        guest_count = sum(len(hypervisor.guestIds) for hypervisor in mapping['hypervisors'])
        self.logger.info('Sending update in hosts-to-guests mapping for config '
                         '"%s": %d hypervisors and %d guests found',
                         report.config.name, hypervisor_count, guest_count)
        self.logger.debug("Host-to-guest mapping: %s", json.dumps(serialized_mapping, indent=4))
        try:
            try:
                result = self.connection.hypervisorCheckIn(report.config.owner, report.config.env, serialized_mapping, options=options)  # pylint:disable=unexpected-keyword-arg
            except TypeError:
                # This is temporary workaround until the options parameter gets implemented
                # in python-rhsm
                self.logger.debug("hypervisorCheckIn method in python-rhsm doesn't understand options paramenter, ignoring")
                result = self.connection.hypervisorCheckIn(report.config.owner, report.config.env, serialized_mapping)
        except BadStatusLine:
            raise ManagerError("Communication with subscription manager interrupted")
        except rhsm_connection.RateLimitExceededException as e:
            retry_after = int(getattr(e, 'headers', {}).get('Retry-After', '60'))
            raise ManagerThrottleError(retry_after)
        except rhsm_connection.GoneException:
            raise ManagerError("Communication with subscription manager failed: consumer no longer exists")
        except rhsm_connection.ConnectionException as e:
            if hasattr(e, 'code'):
                raise ManagerError("Communication with subscription manager failed with code %d: %s" % (e.code, str(e)))
            raise ManagerError("Communication with subscription manager failed: %s" % str(e))
        if is_async is True:
            report.state = AbstractVirtReport.STATE_PROCESSING
            report.job_id = result['id']
        else:
            report.state = AbstractVirtReport.STATE_FINISHED
        return result

    def check_report_state(self, report):
        job_id = report.job_id
        self._connect(report.config)
        self.logger.debug('Checking status of job %s', job_id)
        try:
            result = self.connection.getJob(job_id)
        except BadStatusLine:
            raise ManagerError("Communication with subscription manager interrupted")
        except rhsm_connection.ConnectionException as e:
            if hasattr(e, 'code'):
                raise ManagerError("Communication with subscription manager failed with code %d: %s" % (e.code, str(e)))
            raise ManagerError("Communication with subscription manager failed: %s" % str(e))
        state = STATE_MAPPING.get(result['state'], AbstractVirtReport.STATE_FAILED)
        report.state = state
        if state not in (AbstractVirtReport.STATE_FINISHED,
                         AbstractVirtReport.STATE_CANCELED,
                         AbstractVirtReport.STATE_FAILED):
            self.logger.debug('Job %s not finished', job_id)
        else:
            # log completed job status
            resultData = result.get('resultData', {})
            if not resultData:
                self.logger.warning("Job status report without resultData: %s", result)
                return
            for fail in resultData.get('failedUpdate', []):
                self.logger.error("Error during update list of guests: %s", str(fail))
            for updated in resultData.get('updated', []):
                guests = [x['guestId'] for x in updated['guestIds']]
                self.logger.debug("Updated host %s with guests: [%s]",
                                  updated['uuid'],
                                  ", ".join(guests))
            for created in resultData.get('created', []):
                guests = [x['guestId'] for x in created['guestIds']]
                self.logger.debug("Created host: %s with guests: [%s]",
                                  created['uuid'],
                                  ", ".join(guests))
            self.logger.debug("Number of mappings unchanged: %d", len(resultData.get('unchanged', [])))
            self.logger.info("Mapping for config \"%s\" updated", report.config.name)

    def uuid(self):
        """ Read consumer certificate and get consumer UUID from it. """
        if not self.cert_uuid:
            try:
                certificate = rhsm_certificate.create_from_file(self.cert_file)
                self.cert_uuid = certificate.subject["CN"]
            except Exception as e:
                raise SubscriptionManagerError("Unable to open certificate %s (%s):" % (self.cert_file, str(e)))
        return self.cert_uuid
