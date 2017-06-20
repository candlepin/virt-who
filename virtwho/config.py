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

import collections
import os
from ConfigParser import SafeConfigParser, NoOptionError, Error, MissingSectionHeaderError
from virtwho import log
from password import Password
from binascii import unhexlify
import hashlib
import json
import util

# Module-level logger
logger = log.getLogger('config', queue=False)

_effective_config = None

VW_CONF_DIR = "/etc/virt-who.d/"
VW_TYPES = ("libvirt", "vdsm", "esx", "rhevm", "hyperv", "fake", "xen")
VW_GENERAL_CONF_PATH = "/etc/virt-who.conf"
VW_GLOBAL = "global"
VW_VIRT_DEFAULTS_SECTION_NAME = "defaults"
VW_ENV_CLI_SECTION_NAME = "env/cmdline"

# Default interval for sending list of UUIDs
DefaultInterval = 3600  # One per hour
MinimumSendInterval = 60  # One minute


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
    def from_file(cls, filename):
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
        'print': False,
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
        'print'
        'log_per_config'
    )
    INT_OPTIONS = (
        'interval',
    )

    @classmethod
    def from_file(cls, filename):
        global_config = parse_file(filename).get(VW_GLOBAL)
        if not global_config:
            if logger:
                logger.warning(
                    'Unable to find "%s" section in general config file: "%s"\nWill use defaults where required',
                    VW_GLOBAL, filename)
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

        if self._type not in VW_TYPES:
            raise InvalidOption('Invalid type "%s", must be one of following %s' %
                                (self._type, ", ".join(VW_TYPES)))

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
                defaults_from_config = parse_file(VW_GENERAL_CONF_PATH).get(VW_VIRT_DEFAULTS_SECTION_NAME)
                self._defaults = defaults_from_config or {}
            except MissingSectionHeaderError:
                self._defaults = {}
        else:
            self._defaults = defaults
        if config_dir is None:
            config_dir = VW_CONF_DIR
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


def parse_file(filename):
    # Parse a file into a dict of section_name: options_dict
    # options_dict is a dict of option_name: value
    parser = StripQuotesConfigParser()
    fname = parser.read(filename)
    if len(fname) == 0 and logger:
        logger.error("Unable to read configuration file %s", filename)
    sections = parser._sections
    for section in sections:
        if '__name__' in sections[section]:
            del sections[section]['__name__']
    return sections

# Helper methods used to validate parameters given to virt-who
def str_to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ['yes', 'true', 'on', '1']
    raise ValueError("Unable to convert value to boolean")


def non_empty_string(value):
    if not isinstance(value, str):
        raise TypeError("Value is not a string")
    if not value:
        raise ValueError("String is empty")
    return value


def readable(path):
    if not os.access(path, os.R_OK):
        raise ValueError("Path '%s' is not accessible" % path)


def accessible_file(path):
    readable(path)
    if not os.path.isfile(path):
        raise ValueError("Path '%s' does not appear to be a file" % path)


def accessible_dir(path):
    readable(path)
    if not os.path.isdir(path):
        raise ValueError("Path '%s' does not appear to be a directory" % path)


def empty_or_accessible_files(paths):
    if not isinstance(paths, list):
        if not isinstance(paths, str):
            raise TypeError()
        if len(paths) == 0:
            return []
        paths = [paths]
    if len(paths) == 0:
        return paths
    for path in paths:
        accessible_file(path)
    return paths


class ValidationState(object):
    VALID = 'valid'
    INVALID = 'invalid'
    UNKNOWN = 'unknown'
    NEEDS_VALIDATION = 'needs_validation'


class ConfigSection(collections.MutableMapping):
    """
    This represents a section of configuration for virt-who. The interface that it exposes is 
    dictionary like. This object maintains a state attribute. The state shows if the configuration
    section has passed validation, needs validation, or is invalid for some reason.
    """
    # The string representation of all default properties and values
    # Real values should be added in child classes
    DEFAULTS = ()
    REQUIRED = ()

    __marker = object()

    def __init__(self, section_name, wrapper):
        self.section_name = section_name
        self._wrapper = wrapper
        self.defaults = dict(self.DEFAULTS)
        # Those properties that have yet to be validated
        # Any item not in this set but in this ConfigSection is validated
        self._unvalidated_keys = set()
        self._invalid_keys = set()
        # Holds all properties for this section
        self._values = {}
        # Validation messages from last run
        self.validation_messages = []
        # Add section defaults
        for key, value in self.defaults.items():
            self._values[key] = value
            self._unvalidated_keys.add(key)
        self._update_state()

    def iteritems(self):
        for key in self:
            yield (key, self._values[key])

    def items(self):
        return [(key, self[key]) for key in self]

    def __iter__(self):
        return iter(self._values.keys())

    def _update_state(self):
        if len(self._unvalidated_keys) > 0:
            self.state = ValidationState.NEEDS_VALIDATION
        elif len(self._invalid_keys) > 0 or len(self._values) == 0:
            self.state = ValidationState.INVALID
        else:
            self.state = ValidationState.VALID

    def __delitem__(self, key):
        if key in self:
            if self.has_default(key):
                return
            del self._values[key]
            if key in self._unvalidated_keys:
                self._unvalidated_keys.remove(key)
            if key in self._invalid_keys:
                self._invalid_keys.remove(key)
            self._update_state()
        else:
            raise KeyError('Unable to delete nonexistant property "%s"' % key)

    def __setitem__(self, key, value):
        if key not in self or (key in self and self[key] != value):
            self._unvalidated_keys.add(key)
            self._values[key] = value
            self._update_state()

    def __len__(self):
        return len(self._values)

    def __getitem__(self, key):
        return self._values[key]

    def validate(self, validation_messages=None):
        validation_messages = validation_messages or []
        # Do validation in subclasses
        self.validation_messages = validation_messages
        # Finally calls _update_state
        self._update_state()
        return validation_messages

    def is_default(self, key):
        return self.defaults[key] == self._values[key]

    def has_default(self, key):
        return key in self.defaults

    def get(self, key, default=__marker):
        try:
            return self[key]
        except KeyError as e:
            if default is not self.__marker:
                return default
            raise e

    def __str__(self):
        return_string = "[%s]" % self.section_name
        for key, value in self.iteritems():
            return_string += "\n%s=%s" % (key, value)
        return return_string

    def update(self, *args, **kwds):
        """
        This method implements update as usually defined on a regular dict. The only difference 
        is a refernce to self is expected.
        :param *args: Each arg passed if it has a "keys" method we will do the following d[k] = 
            arg[k] for k in arg.keys. If not we treat the arg as iterable (possiblly a tuple of 
            tuples or list of tuples etc). In this case we do the following: for key, val in arg:
            d[key] = value. 
        :param **kwds: for each keyword arg in kwds we set d[keyword] = kwds[keyword] 
        :return: Nothing
        """
        for arg in args:
            if getattr(arg, 'keys', None):
                for key in arg.keys():
                    self._values[key] = arg[key]
            else:
                for key, value in arg:
                    self._values[key] = value
        for key, value in kwds.items():
            self._values[key] = value

    @classmethod
    def get_defaults(cls):
        """
        Returns: A dictionary of the defaults defined for a ConfigSection of this type.
                 Strings are returned so as to match the values returned by parsers for other 
                 sources of configuration (for example, ConfigParsers or argparse). Better to 
                 treat args from all parsers as strings and to convert from strings 
                 in one place than to check type multiple places up until then.
        """
        defaults = dict()
        for key, value in cls.DEFAULTS:
            defaults[key] = str(value)
        return defaults

    @classmethod
    def class_for_type(cls, virt_type):
        clazz = ConfigSection
        # TODO: Update to use actual subclasses as the are created
        for subclass in cls.__subclasses__():
            if subclass.VIRT_TYPE == virt_type:
                clazz = subclass
                break
        return clazz

    @classmethod
    def from_dict(cls, values, section_name, wrapper):
        virt_type = values.get('virttype', None) or values.get('type')
        return cls.class_for_type(virt_type)(section_name, wrapper)


class GlobalSection(ConfigSection):
    DEFAULTS = (
        ('debug', False),
        ('oneshot', False),
        ('print', False),
        ('log_per_config', False),
        ('background', False),
        ('configs', None),
        ('reporter_id', util.generateReporterId()),
        ('interval', DefaultInterval),
        ('log_file', log.DEFAULT_LOG_FILE),
        ('log_dir', log.DEFAULT_LOG_DIR),
    )
    SECTION_NAME = VW_GLOBAL

    def _validate_interval(self):
        result = None
        try:
            self._values['interval'] = int(self._values['interval'])

            if self._values['interval'] < MinimumSendInterval:
                message = "Interval value can't be lower than {min} seconds. Default value of " \
                          "{min} " \
                          "seconds will be used.".format(min=MinimumSendInterval)
                result = ("warning", message)
                self._values['interval'] = MinimumSendInterval
        except (TypeError, ValueError) as e:
            result = ('warning', 'interval was not set to a valid integer: %s' % str(e))
        return result

    def _validate_str_to_bool(self, key):
        result = None
        try:
            self._values[key] = str_to_bool(self._values[key])
        except (KeyError, ValueError):
            if self.has_default(key):
                self._values[key] = str_to_bool(self.defaults[key])
            result = ('warning', '%s must be a valid boolean, using default. '
                                                   'See man virt-who-config for more info')
        return result

    def _validate_configs(self):
        result = None
        if self.is_default('configs'):
            self._values['configs'] = []
        elif isinstance(self['configs'], list):
            filtered_items = [item for item in self._values['configs'] if isinstance(item, str)]
            self._values['configs'] = filtered_items
        elif isinstance(self._values['configs'], str):
            self._values['configs'] = self._values['configs'].split(',')
        else:
            result = ('warning', '"configs" must be one or more strings, '
                                                   'ignoring')
            self._values['configs'] = []  # Reset to empty list
        return result

    def _validate_non_empty_string(self, key):
        result = None
        if not isinstance(self._values[key], str):
            result = ('warning', '%s is not set to a valid string, using default' % key)
        elif len(self._values[key]) == 0:
            result = ('warning', '%s cannot be empty, using default' % key)
        return result

    def validate(self, validation_messages=None):
        validation_messages = super(GlobalSection, self).validate(validation_messages)
        to_reset = set()
        # Validate those keys that need to be validated
        for key in set(self._unvalidated_keys):
            error = None
            # Handle boolean parameters
            if key in ['debug', 'oneshot', 'print', 'log_per_config', 'background']:
                error = self._validate_str_to_bool(key)
            # Handle configs parameter
            elif key == 'configs':
                error = self._validate_configs()
            # Handle string parameters
            elif key in ['reporter_id', 'log_file', 'log_dir']:
                error = self._validate_non_empty_string(key)
            # Handle interval parameter
            elif key == 'interval':
                error = self._validate_interval()
            else:
                # We must not know of this parameter for the GlobalSection
                validation_messages.append(('warning', 'Ignoring unknown configuration option '
                                                       '"%s"' % key))
                del self._values[key]
            if error is not None:
                validation_messages.append(error)
                if key not in ['interval']:  # Special cases not reset to default on failure
                    to_reset.add(key)
                self._invalid_keys.add(key)
            self._unvalidated_keys.remove(key)

        for key in to_reset:
            if self.has_default(key):
                self._values[key] = self.defaults[key]
                if key in self._invalid_keys:
                    self._invalid_keys.remove(key)

        if self._values['print']:
            self._values['oneshot'] = True

        self._update_state()
        self.validation_messages = validation_messages

        return validation_messages

# String representations of all the default configuration for virt-who
DEFAULTS = {
    VW_GLOBAL: GlobalSection.get_defaults(),
    VW_ENV_CLI_SECTION_NAME: {
        'smtype': 'sam',
    },
}


class EffectiveConfig(collections.MutableMapping):
    """
    This object represents the total configuration of virt-who including all global parameters
    and all sections that define a source or destination.
    """

    __marker = object()

    def __iter__(self):
        return iter(self._sections)

    def __delitem__(self, key):
        if key in self:
            del self[key]
        else:
            raise KeyError("Unable to delete nonexistant section '%s'" % key)

    def __setitem__(self, key, value):
        self._sections[key] = value

    def __len__(self):
        return len(self._sections)

    def __getitem__(self, key):
        return self._sections[key]

    def __contains__(self, item):
        return item in self._sections

    def items(self):
        return [(key, self[key]) for key in self]

    def __init__(self):
        self.validation_messages = []
        self._sections = {}

    def validate(self):
        validation_messages = []
        for section_name, section in self._sections.items():
            # This next check will not be necessary after we know that all sections are
            # ConfigSections
            if getattr(section, 'validate', None) is not None:
                section.validate(validation_messages=validation_messages)
        self.validation_messages = validation_messages
        return validation_messages

    @staticmethod
    def filter_parameters(desired_parameters, values_to_filter):
        matching_parameters = {}
        non_matching_parameters = {}
        for param, value in values_to_filter.iteritems():
            if value is None:
                continue
            value = str(value)
            if param in desired_parameters:
                matching_parameters[param] = value
            else:
                # Take all parameters and their values for those params that are non-default or
                # for which a default is unknown
                non_matching_parameters[param] = value
        return matching_parameters, non_matching_parameters

    @staticmethod
    def all_drop_dir_config_sections():
        """
        Read all configuration sections in the default config directory
        :return: a dictionary of {section_name: {key: value, ... } ... }
        """
        parser = StripQuotesConfigParser()
        all_dir_content = None
        conf_files = None
        non_conf_files = None
        try:
            all_dir_content = set(os.listdir(VW_CONF_DIR))
            conf_files = set(s for s in all_dir_content if s.endswith('.conf'))
            non_conf_files = all_dir_content - conf_files
        except OSError:
            logger.warn("Configuration directory '%s' doesn't exist or is not accessible", VW_CONF_DIR)
            return {}

        if not all_dir_content:
            logger.warn("Configuration directory '%s' appears empty", VW_CONF_DIR)
        elif not conf_files:
            logger.warn("Configuration directory '%s' does not have any '*.conf' files but "
                             "is not empty", VW_CONF_DIR)
        elif non_conf_files:
            logger.debug("There are files in '%s' not ending in '*.conf' is this "
                              "intentional?", VW_CONF_DIR)

        for conf in conf_files:
            if conf.startswith('.'):
                continue
            try:
                filename = parser.read(os.path.join(VW_CONF_DIR, conf))
                if len(filename) == 0:
                    logger.error("Unable to read configuration file %s", conf)
            except MissingSectionHeaderError:
                logger.error("Configuration file %s contains no section headers", conf)
        return parser._sections

    def is_default(self, section, option):
        return self._sections[section].is_default(option)

    def get(self, section, default=__marker):
        return self._sections[section]


def init_config(env_options, cli_options):
    """
    Initialize and return the effective virt-who configuration
    :param env_options: The dict of options parsed from the environment
    :param cli_options: The dict of options parsed from the CLI
    :return: EffectiveConfig
    """
    validation_errors = []
    effective_config = get_effective_config()
    global logger  # Use module level logger as this is likely called before other logging init

    effective_config[VW_GLOBAL] = GlobalSection(VW_GLOBAL, effective_config)
    effective_config[VW_ENV_CLI_SECTION_NAME] = ConfigSection(VW_ENV_CLI_SECTION_NAME,
                                                              effective_config)

    global_required_params = effective_config[VW_GLOBAL].defaults.keys()

    # Split environment variables values into global or non
    env_globals, env_non_globals = effective_config.filter_parameters(global_required_params,
                                                                      env_options)
    # Split cli variables values into global or non
    cli_globals, cli_non_globals = effective_config.filter_parameters(global_required_params,
                                                                      cli_options)
    # Read the virt-who general conf file
    vw_conf = parse_file(VW_GENERAL_CONF_PATH)

    global_section = vw_conf.pop(VW_GLOBAL, {})
    # NOTE: Might be nice in the future to include the defaults in this object
    # So that section would still exist in the output
    virt_defaults_section = vw_conf.pop(VW_VIRT_DEFAULTS_SECTION_NAME, {})
    global_section_sources = [global_section, env_globals, cli_globals]

    for global_source in global_section_sources:
        for key, value in global_source.items():
            if key:
                effective_config[VW_GLOBAL][key.lower()] = value

    # Validate GlobalSection before use.
    validation_errors.extend(effective_config[VW_GLOBAL].validate())

    # Initialize logger, the creation of this object is the earliest it can be done
    log.init(effective_config)
    logger = log.getLogger('config', queue=False)

    # Create the effective env / cli config from those values we've sorted out as non_global
    env_cli_sources = [env_non_globals, cli_non_globals]
    for env_cli_source in env_cli_sources:
        for key, value in env_cli_source.items():
            if key:
                effective_config[VW_ENV_CLI_SECTION_NAME][key.lower()] = value

    # This will add all sections named something other than 'global' or 'defaults' in
    # the main configuration file "/etc/virt-who.conf"
    for section, values in vw_conf.items():
        new_section = {}
        new_section.update(**virt_defaults_section)
        new_section.update(**values)
        try:
            new_section = ConfigSection.from_dict(new_section, section, effective_config)
        except KeyError:
            # Missing required attribute
            continue
        effective_config[section] = new_section

    # Add each section of each file in the drop directory
    drop_dir_config_sections = effective_config.all_drop_dir_config_sections()
    for section, values in drop_dir_config_sections.items():
        new_section = {}
        new_section.update(**virt_defaults_section)
        new_section.update(**values)
        try:
            new_section = ConfigSection.from_dict(new_section, section, self)
        except KeyError:
            # Missing required attribute
            continue
        effective_config[section] = new_section

    global _effective_config
    _effective_config = effective_config
    effective_config.validate()

    return effective_config


def get_effective_config():
    """
    The effective config virt-who is presently running with. If there is not one, 
    create an empty one. This should likely never be called outside module scope.
    Returns: EffectiveConfig
    """
    global _effective_config
    if _effective_config is not None:
        return _effective_config
    # We don't have one, let us make one
    _effective_config = EffectiveConfig()
    return _effective_config  # Initialize an EffectiveConfig with no options
