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
from ConfigParser import SafeConfigParser, NoOptionError, Error, MissingSectionHeaderError
from password import Password


VIRTWHO_CONF_DIR = "/etc/virt-who.d/"
VIRTWHO_TYPES = ("libvirt", "vdsm", "esx", "rhevm", "hyperv")


class InvalidOption(Error):
    pass


class Config(object):
    def __init__(self, name, type, server=None, username=None, password=None, owner=None, env=None):
        self._name = name
        self._type = type
        if self._type not in VIRTWHO_TYPES:
            raise InvalidOption('Invalid type "%s", must be one of following %s' % (self._type, ", ".join(VIRTWHO_TYPES)))
        self._server = server
        self._username = username
        self._password = password
        self._owner = owner
        self._env = env

    def _read_password(self, name, parser):
        try:
            password = parser.get(name, "password")
        except NoOptionError:
            password = None
        if password is None:
            try:
                crypted = parser.get(name, "encrypted_password")
                password = Password.decrypt(password)
            except NoOptionError:
                return None

    @classmethod
    def fromParser(self, name, parser):
        type = parser.get(name, "type").lower()
        server = username = password = owner = env = None
        if type != 'libvirt':
            server = parser.get(name, "server")
            username = parser.get(name, "username")

            try:
                password = parser.get(name, "password")
            except NoOptionError:
                password = None
            if password is None:
                try:
                    crypted = parser.get(name, "encrypted_password")
                    password = Password.decrypt(crypted)
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
        return Config(name, type, server, username, password, owner, env)

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


class ConfigManager(object):
    def __init__(self, config_dir=VIRTWHO_CONF_DIR):
        self._parser = SafeConfigParser()
        self._configs = []
        try:
            config_dir_content = os.listdir(config_dir)
        except OSError:
            logging.warn("Configuration directory '%s' doesn't exist or is not accessible" % config_dir)
            return
        for conf in config_dir_content:
            try:
                filename = self._parser.read(os.path.join(config_dir, conf))
                if len(filename) == 0:
                    logging.error("Unable to read configuration file %s" % conf)
            except MissingSectionHeaderError:
                logging.error("Configuration file %s contains no section headers" % conf)

        self._readConfig()

    def _readConfig(self):
        self._configs = []
        for section in self._parser.sections():
            try:
                config = Config.fromParser(section, self._parser)
                self._configs.append(config)
            except NoOptionError, e:
                logging.error(str(e))

    @property
    def configs(self):
        return self._configs

    def addConfig(self, config):
        self._configs.append(config)
