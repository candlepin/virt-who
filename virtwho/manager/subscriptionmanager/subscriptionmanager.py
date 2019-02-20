# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Module for communication with subscription-manager, part of virt-who

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
from six.moves.http_client import BadStatusLine
from six import string_types

import rhsm.connection as rhsm_connection
import rhsm.certificate as rhsm_certificate
import rhsm.config as rhsm_config

from virtwho.config import NotSetSentinel
from virtwho.manager import Manager, ManagerError, ManagerFatalError, ManagerThrottleError
from virtwho.virt import AbstractVirtReport
from virtwho.util import generate_correlation_id


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
    'WAITING': AbstractVirtReport.STATE_PROCESSING,
    'CREATED': AbstractVirtReport.STATE_PROCESSING,
}


class NamedOptions(object):
    """
    Object used for compatibility with RHSM
    """
    pass


class SubscriptionManager(Manager):
    sm_type = "sam"

    """ Class for interacting subscription-manager. """
    def __init__(self, logger, options):
        self.logger = logger
        self.options = options
        self.cert_uuid = None
        self.rhsm_config = None
        self.cert_file = None
        self.key_file = None
        self.readConfig()
        self.connection = None
        self.correlation_id = generate_correlation_id()

    def readConfig(self):
        """ Parse rhsm.conf in order to obtain consumer
            certificate and key paths. """
        self.rhsm_config = rhsm_config.initConfig(
            rhsm_config.DEFAULT_CONFIG_PATH)
        consumer_cert_dir = self.rhsm_config.get("rhsm", "consumerCertDir")
        cert = 'cert.pem'
        key = 'key.pem'
        self.cert_file = os.path.join(consumer_cert_dir, cert)
        self.key_file = os.path.join(consumer_cert_dir, key)

    def _check_owner_lib(self, kwargs, config):
        """
        Try to check values of env and owner. These values has to be
        equal to values obtained from Satellite server.
        :param kwargs: dictionary possibly containing valid username and
                       password used for connection to rhsm
        :param config: Configuration of virt-who
        :return: None
        """

        if config is None:
            return

        # Check 'owner' and 'env' only in situation, when these values
        # are set and rhsm_username and rhsm_password are not set
        if 'username' not in kwargs and 'password' not in kwargs and \
                'owner' in config.keys() and 'env' in config.keys():
            pass
        else:
            return

        uuid = self.uuid()
        consumer = self.connection.getConsumer(uuid)

        if 'environment' in consumer:
            environment = consumer['environment']
        else:
            return

        if environment:
            environment_name = environment['name']
            owner = self.connection.getOwner(uuid)
            owner_id = owner['key']

            if config['owner'] != owner_id:
                raise ManagerError(
                    "Cannot send data to: %s, because owner from configuration: %s is different" %
                    (owner_id, config['owner'])
                )

            if config['env'] != environment_name:
                raise ManagerError(
                    "Cannot send data to: %s, because Satellite env: %s differs from configuration: %s" %
                    (owner_id, environment_name, config['env'])
                )

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
            'no_proxy': self.rhsm_config.get('server', 'no_proxy'),
            'insecure': self.rhsm_config.get('server', 'insecure')
        }
        kwargs_to_config = {
            'host': 'rhsm_hostname',
            'ssl_port': 'rhsm_port',
            'handler': 'rhsm_prefix',
            'proxy_hostname': 'rhsm_proxy_hostname',
            'proxy_port': 'rhsm_proxy_port',
            'proxy_user': 'rhsm_proxy_user',
            'proxy_password': 'rhsm_proxy_password',
            'no_proxy': 'rhsm_no_proxy',
            'insecure': 'rhsm_insecure'
        }

        rhsm_username = None
        rhsm_password = None

        if config:
            try:
                rhsm_username = config['rhsm_username']
                rhsm_password = config['rhsm_password']
            except KeyError:
                pass

            if rhsm_username == NotSetSentinel:
                rhsm_username = None
            if rhsm_password == NotSetSentinel:
                rhsm_password = None

            # Testing for None is necessary, it might be an empty string
            for key, value in kwargs.items():
                try:
                    from_config = config[kwargs_to_config[key]]
                    if from_config is not NotSetSentinel and from_config is \
                            not None:
                        if key is 'ssl_port':
                            from_config = int(from_config)
                        kwargs[key] = from_config
                except KeyError:
                    continue

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

        self.logger.info("X-Correlation-ID: %s", self.correlation_id)
        if self.correlation_id:
            kwargs['correlation_id'] = self.correlation_id

        self.connection = rhsm_connection.UEPConnection(**kwargs)
        try:
            if not self.connection.ping()['result']:
                raise SubscriptionManagerError(
                    "Unable to obtain status from server, UEPConnection is likely not usable."
                )
        except rhsm_connection.RateLimitExceededException as e:
            raise ManagerThrottleError(e.retry_after)
        except BadStatusLine:
            raise ManagerError("Communication with subscription manager interrupted")

        self._check_owner_lib(kwargs, config)

        return self.connection

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
            raise ManagerThrottleError(e.retry_after)
        report.state = AbstractVirtReport.STATE_FINISHED

    def hypervisorCheckIn(self, report, options=None):
        """ Send hosts to guests mapping to subscription manager. """
        connection = self._connect(report.config)

        is_async = self._is_rhsm_server_async(report, connection)
        serialized_mapping = self._hypervisor_mapping(report, is_async, connection)
        self.logger.debug("Host-to-guest mapping being sent to '{owner}': {mapping}".format(
                          owner=report.config['owner'],
                          mapping=json.dumps(serialized_mapping, indent=4)))

        # All subclasses of ConfigSection use dictionary like notation,
        # but RHSM uses attribute like notation
        if options:
            named_options = NamedOptions()
            for key, value in options['global'].items():
                setattr(named_options, key, value)
        else:
            named_options = None

        try:
            try:
                result = self.connection.hypervisorCheckIn(
                    report.config['owner'],
                    report.config['env'],
                    serialized_mapping,
                    options=named_options)  # pylint:disable=unexpected-keyword-arg
            except TypeError:
                # This is temporary workaround until the options parameter gets implemented
                # in python-rhsm
                self.logger.debug(
                    "hypervisorCheckIn method in python-rhsm doesn't understand options parameter, ignoring"
                )
                result = self.connection.hypervisorCheckIn(report.config['owner'], report.config['env'], serialized_mapping)
        except BadStatusLine:
            raise ManagerError("Communication with subscription manager interrupted")
        except rhsm_connection.RateLimitExceededException as e:
            raise ManagerThrottleError(e.retry_after)
        except rhsm_connection.GoneException:
            raise ManagerError("Communication with subscription manager failed: consumer no longer exists")
        except rhsm_connection.ConnectionException as e:
            if hasattr(e, 'code'):
                raise ManagerError("Communication with subscription manager failed with code %d: %s" % (e.code, str(e)))
            raise ManagerError("Communication with subscription manager failed: %s" % str(e))

        if is_async is True:
            report.state = AbstractVirtReport.STATE_CREATED
            report.job_id = result['id']
        else:
            report.state = AbstractVirtReport.STATE_FINISHED
        return result

    def _is_rhsm_server_async(self, report, connection=None):
        """
        Check if server has capability 'hypervisor_async'.
        """
        if connection is None:
            self._connect(report.config)

        self.logger.debug("Checking if server has capability 'hypervisor_async'")
        is_async = hasattr(self.connection, 'has_capability') and self.connection.has_capability('hypervisors_async')

        if is_async:
            self.logger.debug("Server has capability 'hypervisors_async'")
        else:
            self.logger.debug("Server does not have 'hypervisors_async' capability")

        return is_async

    def _hypervisor_mapping(self, report, is_async, connection=None):
        """
        Return mapping of hypervisor
        """
        if connection is None:
            self._connect(report.config)

        mapping = report.association
        serialized_mapping = {}
        ids_seen = []

        if is_async:
            hosts = []
            # Transform the mapping into the async version
            for hypervisor in mapping['hypervisors']:
                if hypervisor.hypervisorId in ids_seen:
                    self.logger.warning("The hypervisor id '%s' is assigned to 2 different systems. "
                        "Only one will be recorded at the server." % hypervisor.hypervisorId)
                hosts.append(hypervisor.toDict())
                ids_seen.append(hypervisor.hypervisorId)
            serialized_mapping = {'hypervisors': hosts}
        else:
            # Reformat the data from the mapping to make it fit with
            # the old api.
            for hypervisor in mapping['hypervisors']:
                if hypervisor.hypervisorId in ids_seen:
                    self.logger.warning("The hypervisor id '%s' is assigned to 2 different systems. "
                        "Only one will be recorded at the server." % hypervisor.hypervisorId)
                guests = [g.toDict() for g in hypervisor.guestIds]
                serialized_mapping[hypervisor.hypervisorId] = guests
                ids_seen.append(hypervisor.hypervisorId)

        return serialized_mapping

    def check_report_state(self, report):
        # BZ 1554228
        job_id = str(report.job_id)
        self._connect(report.config)
        self.logger.debug('Checking status of job %s', job_id)
        try:
            result = self.connection.getJob(job_id)
        except BadStatusLine:
            raise ManagerError("Communication with subscription manager interrupted")
        except rhsm_connection.RateLimitExceededException as e:
            raise ManagerThrottleError(e.retry_after)
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
            result_data = result.get('resultData', {})
            if not result_data:
                self.logger.warning("Job status report without resultData: %s", result)
                return
            if isinstance(result_data, string_types):
                self.logger.warning("Job status report encountered the following error: %s", result_data)
                return
            for fail in result_data.get('failedUpdate', []):
                self.logger.error("Error during update list of guests: %s", str(fail))
            self.logger.debug("Number of mappings unchanged: %d", len(result_data.get('unchanged', [])))
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
