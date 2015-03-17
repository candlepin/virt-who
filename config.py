"""
Module for reading configuration files

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
import logging
from csv import reader

from ConfigParser import SafeConfigParser, NoOptionError, Error, MissingSectionHeaderError
from password import Password
from binascii import unhexlify

VIRTWHO_CONF_DIR = "/etc/virt-who.d/"
VIRTWHO_TYPES = ("libvirt", "vdsm", "esx", "rhevm", "hyperv", "fake")


class InvalidOption(Error):
    pass


def parse_list(s):
    '''
    Parse comma-separated list of items that might be in double-quotes to the list of strings
    '''
    return reader([s]).next()

class Config(object):
    def __init__(self, name, type, server=None, username=None, password=None, owner=None, env=None, rhsm_username=None, rhsm_password=None):
        self._name = name
        self._type = type
        if self._type not in VIRTWHO_TYPES:
            raise InvalidOption('Invalid type "%s", must be one of following %s' % (self._type, ", ".join(VIRTWHO_TYPES)))
        if server is None and self._type == 'libvirt':
            self._server = ''
        else:
            self._server = server
        self._username = username
        self._password = password
        self._owner = owner
        self._env = env
        self._rhsm_username = rhsm_username
        self._rhsm_password = rhsm_password

        self.filter_host_uuids = []
        self.exclude_host_uuids = []

        self.hypervisor_id = 'uuid'

        # Optional options for backends
        self.filter_host_parents = []
        self.exclude_host_parents = []
        self.esx_simplified_vim = True
        self.fake_is_hypervisor = True
        self.fake_file = None

    @classmethod
    def fromParser(self, name, parser):
        type = parser.get(name, "type").lower()
        server = username = password = owner = env = \
            rhsm_username = rhsm_password = None
        try:
            server = parser.get(name, "server")
        except NoOptionError:
            # Use '' as libvirt url when not given, for backward compatibility
            if type in ['libvirt', 'vdsm', 'fake']:
                server = ''
            else:
                raise
        try:
            username = parser.get(name, "username")
        except NoOptionError:
            username = None

        try:
            password = parser.get(name, "password")
        except NoOptionError:
            password = None
        if password is None:
            try:
                crypted = parser.get(name, "encrypted_password")
                password = Password.decrypt(unhexlify(crypted))
            except NoOptionError:
                password = None

        try:
            owner = parser.get(name, "owner")
        except NoOptionError:
            owner = None
        try:
            env = parser.get(name, "env")
        except NoOptionError:
            env = None

        try:
            rhsm_username = parser.get(name, "rhsm_username")
        except NoOptionError:
            rhsm_username = None

        try:
            rhsm_password = parser.get(name, "rhsm_password")
        except NoOptionError:
            rhsm_password = None

        # Only attempt to get the encrypted rhsm password if we have a username:
        if rhsm_username is not None and rhsm_password is None:
            try:
                crypted = parser.get(name, "rhsm_encrypted_password")
                rhsm_password = Password.decrypt(unhexlify(crypted))
            except NoOptionError:
                rhsm_password = None

        config = Config(name, type, server, username, password, owner, env, rhsm_username, rhsm_password)

        try:
            config.hypervisor_id = parser.get(name, "hypervisor_id")
        except NoOptionError:
            config.hypervisor_id = "uuid"

        try:
            config.filter_host_uuids = parse_list(parser.get(name, "filter_host_uuids"))
        except NoOptionError:
            config.filter_host_uuids = []

        try:
            config.exclude_host_uuids = parse_list(parser.get(name, "exclude_host_uuids"))
        except NoOptionError:
            config.exclude_host_uuids = []

        if type == 'esx':
            try:
                config.esx_simplified_vim = parser.get(name, "simplified_vim").lower() not in ("0", "false", "no")
            except NoOptionError:
                pass
            try:
                config.filter_host_parents = parse_list(parser.get(name, "filter_host_parents"))
            except NoOptionError:
                config.filter_host_parents = []

            try:
                config.exclude_host_parents = parse_list(parser.get(name, "exclude_host_parents"))
            except NoOptionError:
                config.exclude_host_parents = []
        elif type == 'fake':
            try:
                config.fake_is_hypervisor = parser.get(name, "is_hypervisor").lower() not in ("0", "false", "no")
            except NoOptionError:
                pass
            config.fake_file = parser.get(name, "file")

        return config

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

    @property
    def server(self):
        return self._server

    @property
    def username(self):
        return self._username

    @property
    def password(self):
        return self._password

    @property
    def owner(self):
        return self._owner

    @property
    def env(self):
        return self._env

    @property
    def rhsm_username(self):
        return self._rhsm_username

    @property
    def rhsm_password(self):
        return self._rhsm_password


class ConfigManager(object):
    def __init__(self, config_dir=VIRTWHO_CONF_DIR):
        parser = SafeConfigParser()
        self._configs = []
        try:
            config_dir_content = os.listdir(config_dir)
        except OSError:
            logging.warn("Configuration directory '%s' doesn't exist or is not accessible", config_dir)
            return
        for conf in config_dir_content:
            try:
                filename = parser.read(os.path.join(config_dir, conf))
                if len(filename) == 0:
                    logging.error("Unable to read configuration file %s", conf)
            except MissingSectionHeaderError:
                logging.error("Configuration file %s contains no section headers", conf)

        self._readConfig(parser)

    def _readConfig(self, parser):
        self._configs = []
        for section in parser.sections():
            try:
                config = Config.fromParser(section, parser)
                self._configs.append(config)
            except NoOptionError as e:
                logging.error(str(e))

    def readFile(self, filename):
        parser = SafeConfigParser()
        fname = parser.read(filename)
        if len(fname) == 0:
            logging.error("Unable to read configuration file %s", filename)
        self._readConfig(parser)

    @property
    def configs(self):
        return self._configs

    def addConfig(self, config):
        self._configs.append(config)