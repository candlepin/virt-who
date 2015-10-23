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
from csv import reader

from ConfigParser import SafeConfigParser, NoOptionError, Error, MissingSectionHeaderError
from password import Password
from binascii import unhexlify
import hashlib
import json

VIRTWHO_CONF_DIR = "/etc/virt-who.d/"
VIRTWHO_TYPES = ("libvirt", "vdsm", "esx", "rhevm", "hyperv", "fake")
VIRTWHO_GENERAL_CONF_PATH = "/etc/virt-who.conf"
VIRTWHO_GLOBAL_SECTION_NAME = "global"
VIRTWHO_VIRT_DEFAULTS_SECTION_NAME = "defaults"

class InvalidOption(Error):
    pass


class InvalidPasswordFormat(Exception):
    pass


def parse_list(s):
    '''
    Parse comma-separated list of items that might be in double-quotes to the list of strings
    '''
    def strip_quote(s):
        if s[0] == s[-1] == "'":
            return s[1:-1]
        return s
    return map(strip_quote, reader([s.strip(' ')], skipinitialspace=True).next())


class NotSetSentinel(object):
    """
    An empty object subclass that is meant to be used in place of 'None'.
    We might want to set a config value to 'None'
    """
    pass


class GeneralConfig(object):
    # This dictionary should be filled in for subclasses with option_name: default_value
    DEFAULTS = {}
    # options that are lists should be placed here in subclasses
    LIST_OPTIONS = ()
    # boolean options should be listed here
    BOOL_OPTIONS = ()
    INT_OPTIONS = ()

    def __init__(self, defaults=None, **kwargs):
        options = self.DEFAULTS.copy()
        options.update(defaults or {})
        options.update(kwargs)
        # setting the attribute the normal way causes
        # a reference to the dictionary to appear
        self.__dict__['_options'] = options

    def __getattr__(self, name):
        if name.startswith('_'):
            super(GeneralConfig, self).__getattr__(name)

        value = self._options.get(name, None)
        if value is None:
            if name in self.DEFAULTS:
                return self.DEFAULTS[name]
            else:
                return None
        if name in self.BOOL_OPTIONS:
            return str(value).lower() not in ("0", "false", "no")
        if name in self.LIST_OPTIONS:
            return parse_list(value)
        if name in self.INT_OPTIONS:
            return int(value)
        return value

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super(GeneralConfig, self).__setattr__(name, value)
        else:
            self._options[name] = value

    def update(self, **kwargs):
        '''
        Update _options with the kwargs
        '''
        self.__dict__['_options'].update(kwargs)

    def __getitem__(self, name):
        return self._options[name]

    def __setitem__(self, name, value):
        self._options[name] = value

    def __delitem__(self, name):
        del self._options[name]

    def __contains__(self, name):
        return name in self._options

    @classmethod
    def fromFile(cls, logger, filename):
        raise NotImplementedError()



class GlobalConfig(GeneralConfig):
    """
    This GeneralConfig subclass represents the config file
    that holds the global values used to control virt-who's
    operation.
    """
    DEFAULTS = {
        'debug': False,
        'oneshot': False,
        'print_': False,
        'log_per_config': False,
        'background': False
    }
    LIST_OPTIONS = (
        'configs',
    )
    BOOL_OPTIONS = (
        'debug',
        'oneshot',
        'background',
        'print_'
        'log_per_config'
    )
    INT_OPTIONS = (
        'interval',
    )

    @classmethod
    def fromFile(cls, logger=None, filename=VIRTWHO_GENERAL_CONF_PATH):
        global_config = parseFile(filename, logger=logger).get(VIRTWHO_GLOBAL_SECTION_NAME)
        if not global_config and logger:
            logger.warning('Unable to find "%s" section in general config file: "%s"\nWill use defaults where required' % (VIRTWHO_GLOBAL_SECTION_NAME, filename))
        return cls(**global_config)




class Config(GeneralConfig):
    DEFAULTS = {
        'simplified_vim': True,
        'hypervisor_id': 'uuid',
    }
    LIST_OPTIONS = (
        'filter_host_uuids',
        'exclude_host_uuids',
        'filter_host_parents'
        'exclude_host_parents',
    )
    BOOL_OPTIONS = (
        'is_hypervisor',
        'simplified_vim',
    )

    def __init__(self, name, type, defaults=None, **kwargs):
        super(Config, self).__init__(defaults=defaults, **kwargs)
        self._name = name
        self._type = type

        if self._type not in VIRTWHO_TYPES:
            raise InvalidOption('Invalid type "%s", must be one of following %s' %
                                (self._type, ", ".join(VIRTWHO_TYPES)))

    def checkOptions(self, smType, logger):
        # Server option must be there for ESX, RHEVM, and HYPERV
        if 'server' not in self._options:
            if self.type in ['libvirt', 'vdsm', 'fake']:
                self._options['server'] = ''
            else:
                raise InvalidOption("Option `server` needs to be set in config `%s`" % (self.name))

        # Check for env and owner options, it must be present for SAM
        if (smType is not None and smType == 'sam' and (
                (self.type in ('esx', 'rhevm', 'hyperv')) or
                (self.type == 'libvirt' and self.server) or
                (self.type == 'fake' and self.fake_is_hypervisor))):

            if not self.env:
                raise InvalidOption("Option `env` needs to be set in config `%s`" % (self.name))
            elif not self.owner:
                raise InvalidOption("Option `owner` needs to be set in config `%s`" % (self.name))

        if self.type != 'esx':
            if self.filter_host_parents is not None:
                logger.warn("filter_host_parents is not supported in %s mode, ignoring it", self.type)
            if self.exclude_host_parents is not None:
                logger.warn("exclude_host_parents is not supported in %s mode, ignoring it", self.type)

        if self.type != 'fake':
            if self.is_hypervisor is not None:
                logger.warn("is_hypervisor is not supported in %s mode, ignoring it", self.type)
        else:
            if not self.fake_is_hypervisor:
                if self.env:
                    logger.warn("Option `env` is not used in non-hypervisor fake mode")
                if self.owner:
                    logger.warn("Option `owner` is not used in non-hypervisor fake mode")

        if self.type == 'libvirt':
            if self.server is not None and self.server != '':
                if ('ssh://' in self.server or '://' not in self.server) and self.password:
                    logger.warn("Password authentication doesn't work with ssh transport on libvirt backend, "
                                "copy your public ssh key to the remote machine")
            else:
                if self.env:
                    logger.warn("Option `env` is not used in non-remote libvirt connection")
                if self.owner:
                    logger.warn("Option `owner` is not used in non-remote libvirt connection")

    @classmethod
    def fromParser(self, name, parser, defaults=None):
        options = {}
        for option in parser.options(name):
            options[option] = parser.get(name, option)
        type = options.pop('type').lower()
        config = Config(name, type, defaults, **options)
        return config

    @property
    def hash(self):
        return hashlib.md5(json.dumps(self.__dict__, sort_keys=True)).hexdigest()

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

    def _get_password(self, option_name, encryped_option_name):
        pwd = self._options.get(option_name, None)
        if pwd is None:
            encrypted_password = self._options.get(encryped_option_name, None)
            if encrypted_password is None:
                return None
            try:
                pwd = Password.decrypt(unhexlify(encrypted_password))
            except TypeError:
                raise InvalidPasswordFormat("Password can't be decrypted, possibly corrupted")
        return pwd

    @property
    def password(self):
        return self._get_password('password', 'encrypted_password')

    @property
    def rhsm_password(self):
        return self._get_password('rhsm_password', 'rhsm_encrypted_password')

    @property
    def rhsm_proxy_password(self):
        return self._get_password('rhsm_proxy_password', 'rhsm_encrypted_proxy_password')


class ConfigManager(object):
    def __init__(self, logger, config_dir=None, smType=None, defaults=None):
        if not defaults:
            defaults_from_config = parseFile(VIRTWHO_GENERAL_CONF_PATH).get(VIRTWHO_VIRT_DEFAULTS_SECTION_NAME)
            self._defaults = defaults_from_config or {}
        else:
            self._defaults = defaults
        if config_dir is None:
            config_dir = VIRTWHO_CONF_DIR
        self.smType = smType
        parser = SafeConfigParser()
        self._configs = []
        self.logger = logger
        try:
            config_dir_content = os.listdir(config_dir)
        except OSError:
            self.logger.warn("Configuration directory '%s' doesn't exist or is not accessible", config_dir)
            return
        for conf in config_dir_content:
            try:
                filename = parser.read(os.path.join(config_dir, conf))
                if len(filename) == 0:
                    self.logger.error("Unable to read configuration file %s", conf)
            except MissingSectionHeaderError:
                self.logger.error("Configuration file %s contains no section headers", conf)

        self._readConfig(parser)

    def _readConfig(self, parser):
        self._configs = []
        for section in parser.sections():
            try:
                config = Config.fromParser(section, parser, self._defaults)
                config.checkOptions(self.smType, self.logger)
                self._configs.append(config)
            except NoOptionError as e:
                self.logger.error(str(e))

    def readFile(self, filename):
        parser = SafeConfigParser()
        fname = parser.read(filename)
        if len(fname) == 0:
            self.logger.error("Unable to read configuration file %s", filename)
        self._readConfig(parser)

    @property
    def configs(self):
        return self._configs

    def addConfig(self, config):
        self._configs.append(config)

def getOptions(section, parser):
    options = {}
    for option in parser.options(section):
        options[option] = parser.get(section, option)
    return options

def getSections(parser):
    sections = {}
    for section in parser.sections():
        try:
            sections[section] = getOptions(section, parser)
        except NoOptionError:
            sections[section] = {}
    return sections

def parseFile(filename, logger=None):
    # Parse a file into a dict of section_name: options_dict
    # options_dict is a dict of option_name: value

    parser = SafeConfigParser()
    fname = parser.read(filename)
    if len(fname) == 0 and logger:
           logger.error("Unable to read configuration file %s", filename)
    sections = getSections(parser)
    return sections
