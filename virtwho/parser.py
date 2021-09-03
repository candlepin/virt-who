# -*- coding: utf-8 -*-
from __future__ import print_function

# Agent for reporting virtual guest IDs to subscription-manager
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""
This module is used for parsing command line arguments and reading
configuration from environment variables.
"""

import os
import sys as _sys

from argparse import ArgumentParser, Action

from virtwho import log, SAT5, SAT6
from virtwho.config import NotSetSentinel, init_config, DEFAULTS, VW_ENV_CLI_SECTION_NAME
from virtwho.virt.virt import Virt

# Module-level logger
logger = log.getLogger(name='parser', queue=False)

# List of supported virtualization backends
VIRT_BACKENDS = Virt.hypervisor_types()

SAT5_VM_DISPATCHER = {
    'libvirt': {'owner': False, 'server': False, 'username': False},
    'esx': {'owner': False, 'server': True, 'username': True},
    'rhevm': {'owner': False, 'server': True, 'username': True},
    'hyperv': {'owner': False, 'server': True, 'username': True},
    'kubevirt': {'owner': False, 'server': False, 'username': False, 'kubeconfig': True, 'kubeversion': False, 'insecure': False},
    'ahv': {'owner': False, 'server': False, 'username': False},
}

SAT6_VM_DISPATCHER = {
    'libvirt': {'owner': False, 'server': False, 'username': False},
    'esx': {'owner': True, 'server': True, 'username': True},
    'rhevm': {'owner': True, 'server': True, 'username': True},
    'hyperv': {'owner': True, 'server': True, 'username': True},
    'kubevirt': {'owner': True, 'server': False, 'username': False, 'kubeconfig': True, 'kubeversion': False, 'insecure': False},
    'ahv': {'owner': False, 'server': False, 'username': False},
}


class OptionError(Exception):
    pass


class StoreGroupArgument(Action):
    """
    Custom action for storing argument from argument groups (libvirt, esx, ...)
    """

    def __init__(self, option_strings, dest, **kwargs):
        super(StoreGroupArgument, self).__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        """
        When the argument from group is used, then this argument has to match
        virtualization backend [--libvirt|--esx|--rhevm|--hyperv|--kubevirt|--ahv]
        """
        options = vars(namespace)
        virt_type = options['virt_type']
        if virt_type is not None:
            # When virt_type was specified before this argument, then
            # group argument has to match the virt type
            if option_string.startswith('--' + virt_type + '-'):
                setattr(namespace, self.dest, values)
            else:
                raise OptionError("Argument %s does not match virtualization backend: %s" %
                                  (option_string, virt_type))
        else:
            # Extract virt type from option_string. It should be always
            # in this format: --<virt_type>-<self.dest>. Thus following code is safe:
            temp_virt_type = option_string.lstrip('--').split('-')[0]
            # Save it in temporary attribute. When real virt_type will be found
            # in further CLI argument and it will math temp_virt_type, then
            # it will be saved in namespace.<self.dest> too
            setattr(namespace, temp_virt_type + '-' + self.dest, values)


class StoreVirtType(Action):
    """
    Custom action for storing type of virtualization backend. This action
    is similar to "store_const"
    """

    def __init__(self, option_strings, dest, nargs=0, **kwargs):
        super(StoreVirtType, self).__init__(option_strings, dest, nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        options = vars(namespace)
        virt_type = options['virt_type']
        if virt_type is not None:
            raise OptionError("Error: setting virtualization backend to: %s. It is already set to: %s." %
                              (self.const, virt_type))
        else:
            setattr(namespace, self.dest, self.const)
            wrong_virt_prefixes = []
            if self.const in VIRT_BACKENDS:
                # Following prefixes of virt backends are not allowed in this case
                wrong_virt_prefixes = VIRT_BACKENDS[:]
                wrong_virt_prefixes.remove(self.const)
            # Check if there are any temporary saved arguments and check their correctness
            for key, value in options.items():
                if key.startswith(self.const + '-'):
                    dest = key.split('-')[1]
                    setattr(namespace, dest, value)
                elif wrong_virt_prefixes:
                    for wrong_virt_prefix in wrong_virt_prefixes:
                        if key.startswith(wrong_virt_prefix + '-'):
                            raise OptionError("Argument --%s does not match virtualization backend: %s" %
                                              (key, self.const))


def check_argument_consistency(cli_options):
    """
    Final check of cli options that can not be done in custom actions.
    """
    errors = []
    # These options can be required
    REQUIRED_OPTIONS = ['owner', 'server', 'username']

    virt_type = cli_options.get('virt_type')
    sm_type = cli_options.get('sm_type')

    if sm_type == 'sam':
        VM_DISPATCHER = SAT6_VM_DISPATCHER
    elif sm_type == 'satellite':
        VM_DISPATCHER = SAT5_VM_DISPATCHER
    elif sm_type is None:
        errors.append(('warning', 'Unable to check cli argument consistency, no destination '
                                  'provided'))
        return errors
    else:
        errors.append(('warning', 'Unable to check cli argument consistency, no known destination '
                                  'provided'))
        return errors

    if virt_type is not None:
        for option in REQUIRED_OPTIONS:
            # If this option is required for given type of virtualization and it wasn't set, then raise exception
            if VM_DISPATCHER[virt_type][option] is True and option in cli_options and cli_options[option] == "":
                raise OptionError("Required command line argument: --%s-%s is not set." % (virt_type, option))
    else:
        for key in cli_options.keys():
            for prefix in VIRT_BACKENDS:
                if key.startswith(prefix + '-'):
                    raise OptionError("Argument --%s cannot be set without virtualization backend" % key)
    return errors


def check_env(variable, option, required=True):
    """
    If `option` is empty, check environment `variable` and return its value.
    Exit if it's still empty
    """
    if not option or len(option) == 0:
        option = os.getenv(variable, "").strip()
    if required and (not option or len(option) == 0):
        raise OptionError("Required env. variable: '%s' is not set." % variable)
    return option


def read_vm_backend_env_variables(env_vars):
    """
    Try to read environment variables for virtual manager backend
    :param logger: Object used for logging
    :param env_vars: Dictionary with env_vars
    :return: None
    """
    errors = []

    sm_type = env_vars.get('sm_type', DEFAULTS[VW_ENV_CLI_SECTION_NAME]['sm_type'])
    if sm_type is None:
        # Just don't read the env vars if there is no sm_type specified
        return env_vars, errors

    if sm_type == SAT5:
        env_vars['sat_server'] = os.getenv("VIRTWHO_SATELLITE_SERVER")
        env_vars['sat_username'] = os.getenv("VIRTWHO_SATELLITE_USERNAME")
        env_vars['sat_password'] = os.getenv("VIRTWHO_SATELLITE_PASSWORD")

    if sm_type == SAT5:
        VM_DISPATCHER = SAT5_VM_DISPATCHER
    elif sm_type == SAT6:
        VM_DISPATCHER = SAT6_VM_DISPATCHER
    else:
        errors.append(("warning", "Env"))
        VM_DISPATCHER = {}

    if env_vars.get('virt_type') in VM_DISPATCHER.keys():
        virt_type = env_vars['virt_type']

        keys = ['owner', 'server', 'username', 'password']
        for key in keys:
            if len(env_vars.get(key, '')) == 0:
                env_vars[key] = os.getenv("VIRTWHO_" + virt_type.upper() + "_" + key.upper(), "")

    old_dict = dict(**env_vars)
    # Remove empty values from env_vars
    for key, value in old_dict.items():
        if value is None or value == "":
            del env_vars[key]
    return env_vars, errors


def get_version():
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'version.py')
    version = {}
    with open(version_file) as fp:
        exec(fp.read(), version)
    return "virt-who %s" % version['__version__']


def parse_cli_arguments():
    """
    Try to parse command line arguments
    :return: Tuple with two items. First item is dictionary with options and second item is dictionary with
    default options.
    """
    parser = ArgumentParser(
        usage="virt-who [-d] [-o] [-i INTERVAL] [-p] [-c CONFIGS] [-s] [-j] [--version]",
        description="Agent for reporting virtual guest IDs to subscription manager",
        epilog=(
            "virt-who also reads environment variables. They have the same name as "
            "command line arguments but uppercased, with underscore instead of dash "
            "and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are "
            "considered as disabled, non-empty as enabled."
        )
    )
    parser.add_argument("-d", "--debug", action="store_true", dest="debug", default=False,
                        help="Enable debugging output")
    parser.add_argument("-o", "--one-shot", action="store_true", dest="oneshot", default=False,
                        help="Send the list of guest IDs and exit immediately")
    parser.add_argument("-s", "--status", action="store_true", dest="status", default=False,
                        help="Produce a report to show connection health")
    parser.add_argument("-j", "--json", action="store_true", dest="json", default=False,
                        help="Used with status option to make output in json")
    parser.add_argument("-i", "--interval", dest="interval", default=NotSetSentinel(),
                        help="Acquire list of virtual guest each N seconds. Send if changes are detected.")
    parser.add_argument("-p", "--print", action="store_true", dest="print_", default=False,
                        help="Print the host/guest association obtained from virtualization backend (implies oneshot)")
    parser.add_argument("-c", "--config", action="append", dest="configs", default=[],
                        help="Configuration file that will be processed and will override configuration \n"
                             "from other files. 'global' and 'default' sections are not read in files passed in via \n"
                             "this option, and are only read from /etc/virt-who.conf.\n"
                             " Can be used multiple times")
    parser.add_argument("--version", action="store_true", dest="version", default=False,
                        help="Display the version information and exit")

    # Read option from CLI
    cli_options = vars(parser.parse_args())

    # Final check of CLI arguments
    errors = check_argument_consistency(cli_options)

    # Get all default options
    defaults = vars(parser.parse_args([]))

    def get_non_default_options(_cli_options, _defaults):
        return dict((option, value) for option, value in _cli_options.items()
                    if _defaults.get(option, NotSetSentinel()) != value and value is not None)

    return get_non_default_options(cli_options, defaults), errors, defaults


def parse_options():
    """
    This function parses all options from command line and environment variables
    :return: Tuple of logger and options
    """

    # These options are deprecated
    DEPRECATED_OPTIONS = ['log_per_config', 'log_dir', 'log_file', 'reporter_id', 'virt_type',
                          'owner', 'env', 'server', 'username', 'password',
                          'sat_server', 'sat_username', 'sat_password',  'sm_type']
    VIRT_TYPE_OPTIONS = ['owner', 'server', 'username', 'password']
    SAT_OPTION_MAP = {'sat_server': 'satellite-server', 'sat_username': 'satellite-username', 'sat_password': 'satellite-password'}

    # Read command line arguments first
    cli_options, errors, defaults = parse_cli_arguments()

    if 'version' in cli_options and cli_options['version']:
        print(get_version())
        exit(os.EX_OK)

    if 'status' in cli_options and ('print' in cli_options or 'oneshot' in cli_options):
        print("You may not use the --print or --one-shot options with the --status option.")
        exit(os.EX_USAGE)

    if 'json' in cli_options and 'status' not in cli_options:
        print("The --json option must only be used with the --status option.")
        exit(os.EX_USAGE)

    # Create the effective config that virt-who will use to run
    effective_config = init_config(cli_options)
    # Ensure validation errors during effective config creation are logged
    errors.extend(effective_config.validation_messages)

    logger = log.getLogger(config=effective_config, queue=False)

    used_deprecated_cli_options = []
    for option in DEPRECATED_OPTIONS:
        display_option = option
        if option in cli_options and not cli_options[option] == defaults[option]:
            if option == 'virt_type' or option == 'sm_type':
                display_option = cli_options[option]
            elif any(option in s for s in VIRT_TYPE_OPTIONS):
                display_option = '%s-%s' % (cli_options['virt_type'], option)
            elif option in SAT_OPTION_MAP:
                display_option = SAT_OPTION_MAP[option]
            used_deprecated_cli_options.append(display_option)

    # These two flags set the value of sm_type to the default value ('sam'), so ArgumentParser will not
    # include them in the cli_options list, thus we have to manually check for and add them to
    # the deprecated list for them to be included in the warning:
    if '--satellite6' in _sys.argv:
        used_deprecated_cli_options.append('satellite6')
    if '--sam' in _sys.argv:
        used_deprecated_cli_options.append('sam')

    deprecated_options_msg = (
        "The following cli options: %s are deprecated and will be removed "
        "in the next release. Please see 'man virt-who-config' for details on adding "
        "a configuration section."
    )
    if used_deprecated_cli_options:
        logger.warning(deprecated_options_msg % ', '.join('--' + item for item in used_deprecated_cli_options))

    # Log pending errors
    for err in errors:
        method = getattr(logger, err[0])
        if method is not None and err[0] == 'error':
            method(err[1])

    return logger, effective_config
