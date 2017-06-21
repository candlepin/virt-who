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

from ConfigParser import SafeConfigParser, NoOptionError, Error, MissingSectionHeaderError
from virtwho import DefaultInterval
from password import Password
from binascii import unhexlify
import hashlib
import json
import util

VIRTWHO_CONF_DIR = "/etc/virt-who.d/"
VIRTWHO_TYPES = ("libvirt", "vdsm", "esx", "rhevm", "hyperv", "fake", "xen")
VIRTWHO_GENERAL_CONF_PATH = "/etc/virt-who.conf"
VIRTWHO_GLOBAL_SECTION_NAME = "global"
VIRTWHO_VIRT_DEFAULTS_SECTION_NAME = "defaults"


class InvalidOption(Error):
    pass


class InvalidPasswordFormat(Exception):
    pass


def parse_list(s):
    '''
    Parse comma-separated list of items (that might be in quotes) to the list of strings
    '''
    items = []

    read_to = None  # everything until next `read_to` (single or double
    # quotes) character is one item
    item = []  # characters of current items so far
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == '\\':
            item.append(s[i + 1])
            i += 1
        elif read_to is None:
            if ch in ['"', "'"]:
                # everything until next quote is single item
                read_to = ch
            elif ch == ',':
                items.append(''.join(item))
                item = []
            elif not ch.isspace():
                item.append(ch)
        elif ch == read_to:
            read_to = None
        else:
            item.append(ch)
        i += 1
    if read_to is not None:
        raise ValueError("Unterminated %s sign" % {"'": "single quote", '"': "double quote"}.get(read_to, read_to))
    if item:
        items.append(''.join(item))
    return items


class NotSetSentinel(object):
    """
    An empty object subclass that is meant to be used in place of 'None'.
    We might want to set a config value to 'None'
    """
    pass


class Info(object):
    """
    A class containing keys with values.
    If the kwargs passed to the init of this class do not include all
    required_args, init will fail with a ValueError.

    All required and optional kwargs will be accessible on an instance of
    this object as attributes.
    No required or optional kwargs can start with an '_'.

    This class is used as a base for creating entities that are constituted
    entirely by a set of named values. In the case of virt-who we subclass
    this for all destination objects in order to attempt to pull all required
    info for a given type of destination out of configs and to help determine
    what unique destinations exist across all configurations.
    """
    required_kwargs = ()
    optional_kwargs = ()

    def __init__(self, **kwargs):
        self.__dict__["_options"] = {}
        attributes_to_add = []
        attributes_to_add.extend(type(self).required_kwargs)
        if type(self).optional_kwargs:
            attributes_to_add.extend(type(self).optional_kwargs)

        for arg in attributes_to_add:
            try:
                value = kwargs[arg]
                if value in [None, NotSetSentinel, '']:
                    raise TypeError
                self._options[arg] = value
            except (KeyError, TypeError):
                if arg in type(self).required_kwargs:
                    raise ValueError("Missing required option: %s" % arg)

    def __hash__(self):
        to_hash = []
        for item in self._options.values():
            if isinstance(item, list):
                to_hash.append(tuple(item))
            else:
                to_hash.append(item)
        return hash(tuple(to_hash))

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super(object, self).__setattr__(name, value)
            return
        self._options[name] = value

    def __getattr__(self, name):
        if name.startswith('_'):
            return super(object, self).__getattr__(name)
        item = self._options.get(name, NotSetSentinel)
        if item is NotSetSentinel:
            raise AttributeError("No attribute '%s'" % name)
        else:
            return item

    def __getitem__(self, item):
        try:
            return self.__dict__["_options"][item]
        except KeyError:
            pass
        return NotSetSentinel

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.__dict__['_options'] == self.__dict__['_options']

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return NotImplemented
        return not result

    def __iter__(self):
        for key, value in self.__dict__["_options"].iteritems():
            yield (key, value)

    def keys(self):
        return self.__dict__['_options'].keys()

# Should this be defined in the manager that actually requires these values?
class Satellite5DestinationInfo(Info):
    required_kwargs = (
        "sat_server",
        "sat_username",
        "sat_password",
    )
    optional_kwargs = (
        "filter_hosts",
        "exclude_hosts",
    )


# Should this be defined in the manager that actually requires these values?
class Satellite6DestinationInfo(Info):
    required_kwargs = (
        "env",
        "owner",
    )
    optional_kwargs = (
        "rhsm_hostname",
        "rhsm_port",
        "rhsm_prefix",
        "rhsm_username",
        "rhsm_password",
        "rhsm_proxy_hostname",
        "rhsm_proxy_port",
        "rhsm_proxy_user",
        "rhsm_proxy_password",
        "rhsm_insecure",
    )


class DefaultDestinationInfo(Info):
    pass


default_destination_info = DefaultDestinationInfo()
default_destination_info.name = "default_destination"


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

    def __repr__(self):
        return '{cls}({args!r})'.format(cls=self.__class__.__name__, args=self._options)

    def __getattr__(self, name):
        if name.startswith('_'):
            super(GeneralConfig, self).__getattr__(name)

        value = self._options.get(name, None)
        if value is None or value is NotSetSentinel:
            if name in self.DEFAULTS:
                return self.DEFAULTS[name]
            else:
                return None
        if name in self.BOOL_OPTIONS:
            return str(value).lower() not in ("0", "false", "no")
        if name in self.LIST_OPTIONS:
            if not isinstance(value, list):
                return parse_list(value)
            else:
                return value
        if name in self.INT_OPTIONS:
            return int(value)
        return value

    def __setattr__(self, name, value):
        if isinstance(value, NotSetSentinel):
            return
        if name.startswith('_'):
            super(GeneralConfig, self).__setattr__(name, value)
        else:
            self._options[name] = value

    def keys(self):
        return self.__dict__['_options'].keys()

    def update(self, **kwargs):
        '''
        Update _options with the kwargs
        '''
        self.__dict__['_options'].update([(k, v) for k, v in kwargs.iteritems() if not isinstance(v, NotSetSentinel)])

    def __getitem__(self, name):
        return self._options[name]

    def __setitem__(self, name, value):
        if isinstance(value, NotSetSentinel):
            return
        self._options[name] = value

    def __delitem__(self, name):
        del self._options[name]

    def __contains__(self, name):
        return name in self._options

    def has_options(self, options):
        """
        @param options: A list of strings of options. Returns True if all
        options are included in this config
        @type options: list

        @rtype: bool
        """
        for option in options:
            if not option in self:
                return False
        return True

    @classmethod
    def fromFile(cls, filename, logger):
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
        'background': False,
        'configs': '',
        'reporter_id': util.generateReporterId(),
        'smType': None,
        'interval': DefaultInterval
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
    def fromFile(cls, filename, logger=None):
        global_config = parseFile(filename, logger=logger).get(VIRTWHO_GLOBAL_SECTION_NAME)
        if not global_config:
            if logger:
                logger.warning(
                    'Unable to find "%s" section in general config file: "%s"\nWill use defaults where required',
                    VIRTWHO_GLOBAL_SECTION_NAME, filename)
            global_config = {}
        return cls(**global_config)


class Config(GeneralConfig):
    DEFAULTS = {
        'simplified_vim': True,
        'hypervisor_id': 'uuid',
    }
    LIST_OPTIONS = (
        'filter_hosts',
        'filter_host_uuids',
        'exclude_hosts',
        'exclude_host_uuids',
        'filter_host_parents'
        'exclude_host_parents',
    )
    BOOL_OPTIONS = (
        'is_hypervisor',
        'simplified_vim',
    )
    PASSWORD_OPTIONS = (
        ('encrypted_password', 'password'),
        ('rhsm_encrypted_password', 'rhsm_password'),
        ('rhsm_encrypted_proxy_password', 'rhsm_proxy_password'),
        ('sat_encrypted_password', 'sat_password'),
    )
    RENAMED_OPTIONS = (
        ('filter_host_uuids', 'filter_hosts'),
        ('exclude_host_uuids', 'exclude_hosts'),
    )
    # It is usually required to have username in latin1 encoding
    LATIN1_OPTIONS = (
        'username', 'rhsm_username', 'rhsm_proxy_user', 'sat_username',
    )
    # Password can be usually anything
    UTF8_OPTIONS = (
        'password', 'rhsm_password', 'rhsm_proxy_password', 'sat_password',
    )

    def __init__(self, name, virtwho_type, defaults=None, **kwargs):
        super(Config, self).__init__(defaults=defaults, **kwargs)
        self._name = name
        self._type = virtwho_type

        if self._type not in VIRTWHO_TYPES:
            raise InvalidOption('Invalid type "%s", must be one of following %s' %
                                (self._type, ", ".join(VIRTWHO_TYPES)))

        for password_option, decrypted_option in self.PASSWORD_OPTIONS:
            try:
                pwd = self._options[password_option]
            except KeyError:
                continue
            try:
                self._options[decrypted_option] = Password.decrypt(unhexlify(pwd))
            except (TypeError, IndexError):
                raise InvalidPasswordFormat(
                    "Option \"{option}\" in config named \"{name}\" can't be decrypted, possibly corrupted"
                    .format(option=password_option, name=name))

        for old_name, new_name in self.RENAMED_OPTIONS:
            try:
                self._options[new_name] = self._options[old_name]
            except KeyError:
                pass

        for option in self.LATIN1_OPTIONS:
            value = self._options.get(option)
            if not value or value is NotSetSentinel:
                continue
            try:
                value.encode('latin1')
            except UnicodeDecodeError:
                raise InvalidOption("Value: {0} of option '{1}': is not in latin1 encoding".format(value, option))

        for option in self.UTF8_OPTIONS:
            value = self._options.get(option)
            if not value or value is NotSetSentinel:
                continue
            try:
                value.decode('UTF-8')
            except UnicodeDecodeError:
                raise InvalidOption("Value: {0} of option '{1}': is not in UTF-8 encoding".format(value, option))

    @property
    def smType(self):
        try:
            return self._options['smType']
        except KeyError:
            if 'sat_server' in self._options:
                return 'satellite'
            elif 'rhsm_hostname' in self._options:
                return 'sam'
            else:
                return None

    def checkOptions(self, logger):
        # Server option must be there for ESX, RHEVM, and HYPERV
        if 'server' not in self._options:
            if self.type in ['libvirt', 'vdsm', 'fake']:
                self._options['server'] = ''
            else:
                raise InvalidOption("Option `server` needs to be set in config `%s`" % self.name)

        # Check for env and owner options, it must be present for SAM
        if ((self.smType is None or self.smType == 'sam') and (
                (self.type in ('esx', 'rhevm', 'hyperv', 'xen')) or
                (self.type == 'libvirt' and self.server) or
                (self.type == 'fake' and self.fake_is_hypervisor))):

            if not self.env:
                raise InvalidOption("Option `env` needs to be set in config `%s`" % self.name)
            elif not self.owner:
                raise InvalidOption("Option `owner` needs to be set in config `%s`" % self.name)

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
    def fromParser(cls, name, parser, defaults=None):
        options = {}
        for option in parser.options(name):
            options[option] = parser.get(name, option)
        virtwho_type = options.pop('type').lower()
        config = Config(name, virtwho_type, defaults, **options)
        return config

    @property
    def hash(self):
        return hashlib.sha256(json.dumps(self.__dict__, sort_keys=True)).hexdigest()

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type


class StripQuotesConfigParser(SafeConfigParser):
    def get(self, section, option):
        # Don't call super, SafeConfigParser is not inherited from object
        value = SafeConfigParser.get(self, section, option)
        for quote in ('"', "'"):
            # Strip the quotes only when the value starts with quote,
            # ends with quote but doesn't contain it inside
            if value.startswith(quote) and value.endswith(quote) and quote not in value[1:-1]:
                return value.strip(quote)
        return value


class ConfigManager(object):
    def __init__(self, logger, config_dir=None, defaults=None):
        if not defaults:
            try:
                defaults_from_config = parseFile(VIRTWHO_GENERAL_CONF_PATH).get(VIRTWHO_VIRT_DEFAULTS_SECTION_NAME)
                self._defaults = defaults_from_config or {}
            except MissingSectionHeaderError:
                self._defaults = {}
        else:
            self._defaults = defaults
        if config_dir is None:
            config_dir = VIRTWHO_CONF_DIR
        parser = StripQuotesConfigParser()
        self._configs = []
        self.logger = logger
        self.sources = set()
        self.dests = set()
        self.dest_to_sources_map = {}
        all_dir_content = None
        conf_files = None
        non_conf_files = None
        try:
            all_dir_content = set(os.listdir(config_dir))
            conf_files = set(s for s in all_dir_content if s.endswith('.conf'))
            non_conf_files = all_dir_content - conf_files
        except OSError:
            self.logger.warn("Configuration directory '%s' doesn't exist or is not accessible", config_dir)
            return
        if not all_dir_content:
            self.logger.warn("Configuration directory '%s' appears empty", config_dir)
        elif not conf_files:
            self.logger.warn("Configuration directory '%s' does not have any '*.conf' files but "
                             "is not empty", config_dir)
        elif non_conf_files:
            self.logger.debug("There are files in '%s' not ending in '*.conf' is this "
                              "intentional?", config_dir)

        for conf in conf_files:
            if conf.startswith('.'):
                continue
            try:
                filename = parser.read(os.path.join(config_dir, conf))
                if len(filename) == 0:
                    self.logger.error("Unable to read configuration file %s", conf)
            except MissingSectionHeaderError:
                self.logger.error("Configuration file %s contains no section headers", conf)

        self._readConfig(parser)
        self.update_dest_to_source_map()

    def update_dest_to_source_map(self):
        sources, dests, d_to_s, orphan_sources = \
            ConfigManager.map_destinations_to_sources(
                self._configs)
        if orphan_sources:
            d_to_s[default_destination_info] = orphan_sources
            dests.add(default_destination_info)
        self.sources = sources
        self.dests = dests
        self.dest_to_sources_map = d_to_s

    def _readConfig(self, parser):
        for section in parser.sections():
            try:
                config = Config.fromParser(section, parser, self._defaults)
                config.checkOptions(self.logger)
                self._configs.append(config)
            except NoOptionError as e:
                self.logger.error(str(e))
            except InvalidPasswordFormat as e:
                self.logger.error(str(e))
            except InvalidOption as e:
                # When a configuration section has an Invalid Option, continue
                # See https://bugzilla.redhat.com/show_bug.cgi?id=1457101 for more info
                self.logger.warn("Invalid configuration detected: %s", str(e))

    def readFile(self, filename):
        parser = StripQuotesConfigParser()
        fname = parser.read(filename)
        if len(fname) == 0:
            self.logger.error("Unable to read configuration file %s", filename)
        self._readConfig(parser)

    @staticmethod
    def map_destinations_to_sources(configs, dest_classes=(Satellite5DestinationInfo, Satellite6DestinationInfo)):
        """
        Create a mapping of destinations to sources, given all the collected
        and parsed configuration objects.

        @param configs: A list of Config objects to analyze
        @type configs: list

        @param dest_classes: An iterable of classes to try to pull out of a
        config object
        @type dest_classes: Iterable

        @rtype: (set, set, dict)
        """

        # Will include the names of the configs
        sources = set()
        sources_without_destinations = set()
        # Will include all dest info objects from all configs
        dests = set()
        dest_classes = dest_classes or (Satellite5DestinationInfo,
                                        Satellite6DestinationInfo)
        # We could expand this to include other specific sources
        # For now all configs are considered to define a source at a minimum
        # As such we will consider each config section name to be unique
        dest_to_source_map = {}  # The resultant
        # mapping
        # of destination to
        # sources
        for config in configs:
            sources.add(config.name)
            sources_without_destinations.add(config.name)
            for dest in ConfigManager.parse_dests_from_dict(config._options,
                                                            dest_classes):
                dests.add(dest)
                current_sources = dest_to_source_map.get(dest, set())
                current_sources.update(set([config.name]))
                sources_without_destinations.difference_update(
                        set([config.name]))
                dest_to_source_map[dest] = current_sources
        for dest, source_set in dest_to_source_map.iteritems():
            dest_to_source_map[dest] = sorted(list(source_set))
        sources_without_destinations = sorted(list(sources_without_destinations))
        return sources, dests, dest_to_source_map, sources_without_destinations

    @staticmethod
    def parse_dests_from_dict(dict_to_parse,
                              dest_classes=(
                                Satellite5DestinationInfo,
                                Satellite6DestinationInfo,
                              )):
        """
        @param dict_to_parse: The dict of kwargs to try to create a
        destination out of
        @type dict_to_parse: dict

        @param dest_classes: An iterable of Info classes to try to create
            based on the given dict of options
        @type dest_classes: collections.Iterable

        @return: A set of the info objects that could be created from the
        given dict
        @rtype: set
        """
        dests = set()
        for dest_class in dest_classes:
            dest = None
            try:
                dest = dest_class(**dict_to_parse)
            except ValueError:
                continue
            dests.add(dest)
        return dests

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
    parser = StripQuotesConfigParser()
    fname = parser.read(filename)
    if len(fname) == 0 and logger:
        logger.error("Unable to read configuration file %s", filename)
    sections = getSections(parser)
    return sections


class ConfigHierarchy(object):
    """
    This class represents the hierarchy of configuration information. It holds all parsed
    configuration for the given sources in order of most important to least. An instance of this
    can be used to ensure that it is clear when a config value is used, where it comes from.
    """

    def __init__(self):
        self.hierarchy = []  # The order of precedence for the sources of config info given
        self.config_sources = {}  # A dict of config_source_name -> parsed dict of items

    def get(self, key, **kwargs):
        """
        @param key: The configuration value sought
        @type key: string
        @param default: The value to return should we not find a value
        @return: The value for the given key
        @raises KeyError: When there is no default given and there is no value found for the
        given key
        """
        # TODO: Allow this or another method to return where the value came from
        # This way if validation fails for some reason we can output a useful message
        # as to where the value came from
        for source in self.hierarchy:
            if key in self.config_sources[source]:
                return self.config_sources[source][key]
        if 'default' not in kwargs:
            raise KeyError('Value for key "%s" not found' % key)
        else:
            return kwargs['default']

    def append(self, source_name, values):
        """
        @param source_name: The name used to identify where the values came from
        @type source_name: string
        @param values: The parsed (but not validated) dictionary of attributes provided by the
        source
        @type values: dict

        @return: True if the source was added successfully, false otherwise
        @rtype: bool

        @raises ValueError: A ValueError is raised when the source_name is already tracked
        @raises TypeError: A TypeError is raised when the values provided are not a dict
        """
        if source_name in self.hierarchy:
            raise ValueError("Values have already been added for config source '%s'" % source_name)
        if not isinstance(values, dict):
            raise TypeError("The provided values must be a dict")

        self.hierarchy.append(source_name)
        self.config_sources[source_name] = values

    def remove(self, source_name):
        """
        Removes the source_name from this ConfigHierarchy
        @param source_name: The name used to identify where the values came from
        @type source_name: string
        """
        if source_name in self.hierarchy:
            self.hierarchy.remove(source_name)
        if source_name in self.config_sources:
            del self.config_sources[source_name]
