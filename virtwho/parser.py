# -*- coding: utf-8 -*-

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
from argparse import ArgumentParser, Action

from virtwho import log, MinimumSendInterval, DefaultInterval
from virtwho.config import NotSetSentinel, init_config, DEFAULTS, VW_GLOBAL,\
    VW_ENV_CLI_SECTION_NAME
from virtwho.virt.virt import Virt


SAT5 = "satellite"
SAT6 = "sam"

# List of supported virtualization backends
VIRT_BACKENDS = Virt.hypervisor_types()

SAT_VM_DISPATCHER = {
    'libvirt': {'owner': False, 'env': False, 'server': False, 'username': False},
    'esx': {'owner': False, 'env': False, 'server': True, 'username': True},
    'xen': {'owner': False, 'env': False, 'server': True, 'username': True},
    'rhevm': {'owner': False, 'env': False, 'server': True, 'username': True},
    'hyperv': {'owner': False, 'env': False, 'server': True, 'username': True},
}

SAM_VM_DISPATCHER = {
    'libvirt': {'owner': False, 'env': False, 'server': False, 'username': False},
    'esx': {'owner': True, 'env': True, 'server': True, 'username': True},
    'xen': {'owner': True, 'env': True, 'server': True, 'username': True},
    'rhevm': {'owner': True, 'env': True, 'server': True, 'username': True},
    'hyperv': {'owner': True, 'env': True, 'server': True, 'username': True},
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
        virtualization backend [--libvirt|--vdsm|--esx|--rhevm|--hyperv|--xen]
        """
        options = vars(namespace)
        virt_type = options['virtType']
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
        virt_type = options['virtType']
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
    REQUIRED_OPTIONS = ['owner', 'env', 'server', 'username']

    virt_type = cli_options.get('virtType')
    sm_type = cli_options.get('smType')

    if sm_type == 'sam':
        VM_DISPATCHER = SAM_VM_DISPATCHER
    elif sm_type == 'satellite':
        VM_DISPATCHER = SAT_VM_DISPATCHER
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


def read_config_env_variables():
    """
    This function tries to load environment variables and it will add them to a dictionary
    returned.
    :return: the dictonary of configuration values -> parsed value
    """

    # The dictionary to return
    env_vars = {}

    # Function called by dispatcher
    def store_const(_options, _attr, _env, _const):
        if _env.lower() in ["1", "true"]:
            _options[_attr] = _const

    # Function called by dispatcher
    def store_value(_options, _attr, _env):
        if _env is not None and _env != "":
            _options[_attr] = _env

    # Dispatcher for storing environment values in env_vars object
    dispatcher = {
        # environment variable: (attribute_name, default_value, method, const)
        "VIRTWHO_LOG_PER_CONFIG": ("log_per_config",
                                   store_const, "true"),
        "VIRTWHO_LOG_FILE": ("log_file",
                             store_value),
        "VIRTWHO_DEBUG": ("debug",
                          store_const, "true"),
        "VIRTWHO_BACKGROUND": ("background",
                               store_const,
                               "true"),
        "VIRTWHO_ONE_SHOT": ("oneshot",
                             store_const,
                             "true"),
        "VIRTWHO_SAM": ("smType", store_const, SAT6),
        "VIRTWHO_SATELLITE6": ("smType", store_const, SAT6),
        "VIRTWHO_SATELLITE5": ("smType", store_const, SAT5),
        "VIRTWHO_SATELLITE": ("smType", store_const, SAT5),
        "VIRTWHO_LIBVIRT": ("virtType", store_const, "libvirt"),
        "VIRTWHO_VDSM": ("virtType", store_const, "vdsm"),
        "VIRTWHO_ESX": ("virtType", store_const, "esx"),
        "VIRTWHO_XEN": ("virtType", store_const, "xen"),
        "VIRTWHO_RHEVM": ("virtType", store_const, "rhevm"),
        "VIRTWHO_HYPERV": ("virtType", store_const, "hyperv"),
        "VIRTWHO_INTERVAL": ("interval", store_value),
        "VIRTWHO_REPORTER_ID": ("reporter_id", store_value),
    }

    # Store values of environment variables to env_vars using dispatcher
    for key, values in dispatcher.items():
        attribute = values[0]
        method = values[1]

        if key in os.environ:
            env = os.getenv(key).strip()
            # Try to get const
            try:
                value = values[2]
                method(env_vars, attribute, env, value)
            except IndexError:
                method(env_vars, attribute, env)

    # Todo: move this logic to the EffectiveConfig
    # env = os.getenv("VIRTWHO_LOG_DIR", log.DEFAULT_LOG_DIR).strip()
    # if env != log.DEFAULT_LOG_DIR:
    #     env_vars.log_dir = env
    # elif env_vars.log_per_config:
    #     env_vars.log_dir = os.path.join(log.DEFAULT_LOG_DIR, 'virtwho')
    return env_vars


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

    sm_type = env_vars.get('smType', DEFAULTS[VW_ENV_CLI_SECTION_NAME]['smtype'])
    if sm_type is None:
        # Just don't read the env vars if there is no smType specified
        return env_vars, errors

    if sm_type == SAT5:
        env_vars['sat_server'] = os.getenv("VIRTWHO_SATELLITE_SERVER")
        env_vars['sat_username'] = os.getenv("VIRTWHO_SATELLITE_USERNAME")
        env_vars['sat_password'] = os.getenv("VIRTWHO_SATELLITE_PASSWORD")

    if sm_type == SAT5:
        VM_DISPATCHER = SAM_VM_DISPATCHER
    elif sm_type == SAT6:
        VM_DISPATCHER = SAT_VM_DISPATCHER
    else:
        errors.append(("warning", "Env"))
        VM_DISPATCHER = {}

    if env_vars.get('virtType') in VM_DISPATCHER.keys():
        virt_type = env_vars['virtType']
        try:
            env_vars['owner'] = check_env("VIRTWHO_" + virt_type.upper() + "_OWNER",
                                          env_vars.get('owner'),
                                          required=VM_DISPATCHER[virt_type]['owner'])
            env_vars['env'] = check_env("VIRTWHO_" + virt_type.upper() + "_ENV",
                                        env_vars.get('env'),
                                        required=VM_DISPATCHER[virt_type]['env'])
            env_vars['server'] = check_env("VIRTWHO_" + virt_type.upper() + "_SERVER",
                                           env_vars.get('server'),
                                           required=VM_DISPATCHER[virt_type]['server'])
            env_vars['username'] = check_env("VIRTWHO_" + virt_type.upper() + "_USERNAME",
                                             env_vars.get('username'),
                                             required=VM_DISPATCHER[virt_type]['username'])
        except OptionError as err:
            errors.append(("error", "Error: reading environment variables for virt. type: %s: %s" % (
                env_vars.get('virtType'), err)))
        else:
            if len(env_vars.get('password', '')) == 0:
                env_vars['password'] = os.getenv("VIRTWHO_" + virt_type.upper() + "_PASSWORD", "")
    return env_vars, errors


def parse_cli_arguments():
    """
    Try to parse command line arguments
    :return: Tuple with two items. First item is dictionary with options and second item is dictionary with
    default options.
    """
    parser = ArgumentParser(
        usage="virt-who [-d] [-i INTERVAL] [-o] [--sam|--satellite5|--satellite6] "
              "[--libvirt|--vdsm|--esx|--rhevm|--hyperv|--xen]",
        description="Agent for reporting virtual guest IDs to subscription manager",
        epilog="virt-who also reads environment variables. They have the same name as "
               "command line arguments but uppercased, with underscore instead of dash "
               "and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are "
               "considered as disabled, non-empty as enabled."
    )
    parser.add_argument("-d", "--debug", action="store_true", dest="debug", default=False,
                        help="Enable debugging output")
    parser.add_argument("-o", "--one-shot", action="store_true", dest="oneshot", default=False,
                        help="Send the list of guest IDs and exit immediately")
    parser.add_argument("-i", "--interval", type=int, dest="interval", default=NotSetSentinel(),
                        help="Acquire list of virtual guest each N seconds. Send if changes are detected.")
    parser.add_argument("-p", "--print", action="store_true", dest="print_", default=False,
                        help="Print the host/guest association obtained from virtualization backend (implies oneshot)")
    parser.add_argument("-c", "--config", action="append", dest="configs", default=[],
                        help="Configuration file that will be processed, can be used multiple times")
    parser.add_argument("-m", "--log-per-config", action="store_true", dest="log_per_config", default=NotSetSentinel(),
                        help="[Deprecated] Write one log file per configured virtualization backend.\n"
                             "Implies a log_dir of %s/virtwho (Default: all messages are written to a single log file)"
                             % log.DEFAULT_LOG_DIR)
    parser.add_argument("-l", "--log-dir", action="store", dest="log_dir", default=log.DEFAULT_LOG_DIR,
                        help="[Deprecated] The absolute path of the directory to log to. (Default '%s')" % log.DEFAULT_LOG_DIR)
    parser.add_argument("-f", "--log-file", action="store", dest="log_file", default=log.DEFAULT_LOG_FILE,
                        help="[Deprecated] The file name to write logs to. (Default '%s')" % log.DEFAULT_LOG_FILE)
    parser.add_argument("-r", "--reporter-id", action="store", dest="reporter_id", default=NotSetSentinel(),
                        help="[Deprecated] Label host/guest associations obtained by this instance of virt-who with the provided id.")

    virt_group = parser.add_argument_group(
        title="Virtualization backend",
        description="Choose virtualization backend that should be used to gather host/guest associations"
    )
    virt_group.add_argument("--libvirt", action=StoreVirtType, dest="virtType", const="libvirt",
                            default=None, help="[Deprecated] Use libvirt to list virtual guests")
    virt_group.add_argument("--vdsm", action=StoreVirtType, dest="virtType", const="vdsm",
                            help="[Deprecated] Use vdsm to list virtual guests")
    virt_group.add_argument("--esx", action=StoreVirtType, dest="virtType", const="esx",
                            help="[Deprecated] Register ESX machines using vCenter")
    virt_group.add_argument("--xen", action=StoreVirtType, dest="virtType", const="xen",
                            help="[Deprecated] Register XEN machines using XenServer")
    virt_group.add_argument("--rhevm", action=StoreVirtType, dest="virtType", const="rhevm",
                            help="[Deprecated] Register guests using RHEV-M")
    virt_group.add_argument("--hyperv", action=StoreVirtType, dest="virtType", const="hyperv",
                            help="[Deprecated] Register guests using Hyper-V")

    manager_group = parser.add_argument_group(
        title="Subscription manager",
        description="Choose where the host/guest associations should be reported"
    )
    manager_group.add_argument("--sam", action="store_const", dest="smType", const=SAT6, default=SAT6,
                               help="[Deprecated] Report host/guest associations to the Subscription Asset Manager [default]")
    manager_group.add_argument("--satellite6", action="store_const", dest="smType", const=SAT6,
                               help="[Deprecated] Report host/guest associations to the Satellite 6 server")
    manager_group.add_argument("--satellite5", action="store_const", dest="smType", const=SAT5,
                               help="[Deprecated] Report host/guest associations to the Satellite 5 server")
    manager_group.add_argument("--satellite", action="store_const", dest="smType", const=SAT5)

    # FIXME: Remove all options of virtualization backend. Adding this wasn't happy design decision.
    libvirt_group = parser.add_argument_group(
        title="Libvirt options",
        description="Use these options with --libvirt"
    )
    libvirt_group.add_argument("--libvirt-owner", action=StoreGroupArgument, dest="owner", default="",
                               help="[Deprecated] Organization who has purchased subscriptions of the products, "
                                    "default is owner of current system")
    libvirt_group.add_argument("--libvirt-env", action=StoreGroupArgument, dest="env", default="",
                               help="[Deprecated] Environment where the server belongs to, default is environment of current system")
    libvirt_group.add_argument("--libvirt-server", action=StoreGroupArgument, dest="server", default="",
                               help="[Deprecated] URL of the libvirt server to connect to, default is empty "
                                    "for libvirt on local computer")
    libvirt_group.add_argument("--libvirt-username", action=StoreGroupArgument, dest="username", default="",
                               help="[Deprecated] Username for connecting to the libvirt daemon")
    libvirt_group.add_argument("--libvirt-password", action=StoreGroupArgument, dest="password", default="",
                               help="[Deprecated] Password for connecting to the libvirt daemon")

    esx_group = parser.add_argument_group(
        title="vCenter/ESX options",
        description="Use these options with --esx"
    )
    esx_group.add_argument("--esx-owner", action=StoreGroupArgument, dest="owner", default="",
                           help="[Deprecated] Organization who has purchased subscriptions of the products")
    esx_group.add_argument("--esx-env", action=StoreGroupArgument, dest="env", default="",
                           help="[Deprecated] Environment where the vCenter server belongs to")
    esx_group.add_argument("--esx-server", action=StoreGroupArgument, dest="server", default="",
                           help="[Deprecated] URL of the vCenter server to connect to")
    esx_group.add_argument("--esx-username", action=StoreGroupArgument, dest="username", default="",
                           help="[Deprecated] Username for connecting to vCenter")
    esx_group.add_argument("--esx-password", action=StoreGroupArgument, dest="password", default="",
                           help="[Deprecated] Password for connecting to vCenter")

    rhevm_group = parser.add_argument_group(
        title="RHEV-M options",
        description="Use these options with --rhevm"
    )
    rhevm_group.add_argument("--rhevm-owner", action=StoreGroupArgument, dest="owner", default="",
                             help="[Deprecated] Organization who has purchased subscriptions of the products")
    rhevm_group.add_argument("--rhevm-env", action=StoreGroupArgument, dest="env", default="",
                             help="[Deprecated] Environment where the RHEV-M belongs to")
    rhevm_group.add_argument("--rhevm-server", action=StoreGroupArgument, dest="server", default="",
                             help="[Deprecated] URL of the RHEV-M server to connect to (preferable use secure connection"
                                  "- https://<ip or domain name>:<secure port, usually 8443>)")
    rhevm_group.add_argument("--rhevm-username", action=StoreGroupArgument, dest="username", default="",
                             help="[Deprecated] Username for connecting to RHEV-M in the format username@domain")
    rhevm_group.add_argument("--rhevm-password", action=StoreGroupArgument, dest="password", default="",
                             help="[Deprecated] Password for connecting to RHEV-M")

    hyperv_group = parser.add_argument_group(
        title="Hyper-V options",
        description="Use these options with --hyperv"
    )
    hyperv_group.add_argument("--hyperv-owner", action=StoreGroupArgument, dest="owner", default="",
                              help="[Deprecated] Organization who has purchased subscriptions of the products")
    hyperv_group.add_argument("--hyperv-env", action=StoreGroupArgument, dest="env", default="",
                              help="[Deprecated] Environment where the Hyper-V belongs to")
    hyperv_group.add_argument("--hyperv-server", action=StoreGroupArgument, dest="server",
                              default="", help="[Deprecated] URL of the Hyper-V server to connect to")
    hyperv_group.add_argument("--hyperv-username", action=StoreGroupArgument, dest="username",
                              default="", help="[Deprecated] Username for connecting to Hyper-V")
    hyperv_group.add_argument("--hyperv-password", action=StoreGroupArgument, dest="password",
                              default="", help="[Deprecated] Password for connecting to Hyper-V")

    xen_group = parser.add_argument_group(
        title="XenServer options",
        description="Use these options with --xen"
    )
    xen_group.add_argument("--xen-owner", action=StoreGroupArgument, dest="owner", default="",
                           help="[Deprecated] Organization who has purchased subscriptions of the products")
    xen_group.add_argument("--xen-env", action=StoreGroupArgument, dest="env", default="",
                           help="[Deprecated] Environment where the XenServer belongs to")
    xen_group.add_argument("--xen-server", action=StoreGroupArgument, dest="server", default="",
                           help="[Deprecated] URL of the XenServer server to connect to")
    xen_group.add_argument("--xen-username", action=StoreGroupArgument, dest="username", default="",
                           help="[Deprecated] Username for connecting to XenServer")
    xen_group.add_argument("--xen-password", action=StoreGroupArgument, dest="password", default="",
                           help="[Deprecated] Password for connecting to XenServer")

    satellite_group = parser.add_argument_group(
        title="Satellite 5 options",
        description="Use these options with --satellite5"
    )
    satellite_group.add_argument("--satellite-server", action="store", dest="sat_server", default="",
                                 help="[Deprecated] Satellite server URL")
    satellite_group.add_argument("--satellite-username", action="store", dest="sat_username", default="",
                                 help="[Deprecated] Username for connecting to Satellite server")
    satellite_group.add_argument("--satellite-password", action="store", dest="sat_password", default="",
                                 help="[Deprecated] Password for connecting to Satellite server")


    # Read option from CLI
    cli_options = vars(parser.parse_args())

    # Final check of CLI arguments
    errors = check_argument_consistency(cli_options)

    # Get all default options
    defaults = vars(parser.parse_args([]))

    def get_non_default_options(_cli_options, _defaults):
        return dict((option, value) for option, value in _cli_options.iteritems()
                    if _defaults.get(option, NotSetSentinel()) != value and value is not None)

    return get_non_default_options(cli_options, defaults), errors, defaults


def parse_options():
    """
    This function parses all options from command line and environment variables
    :return: Tuple of logger and options
    """

    # These options are deprecated
    DEPRECATED_OPTIONS = ['log_per_config', 'log_dir', 'log_file', 'reporter_id', 'virtType',
                          'owner', 'env', 'server', 'username', 'password',
                          'sat_server', 'sat_username', 'sat_password',  'smType']
    VIRT_TYPE_OPTIONS = ['owner', 'env', 'server', 'username', 'password']
    SAT_OPTION_MAP = {'sat_server':'satellite-server', 'sat_username':'satellite-username', 'sat_password':'satellite-password'}

    # Read command line arguments first
    cli_options, errors, defaults = parse_cli_arguments()

    # Read configuration env. variables
    env_options = read_config_env_variables()

    # Read environments variables for virtualization backends
    env_options, env_errors = read_vm_backend_env_variables(env_options)
    errors.extend(env_errors)
    # Create the effective config that virt-who will use to run
    effective_config = init_config(env_options, cli_options)
    # Ensure validation errors during effective config creation are logged
    errors.extend(effective_config.validation_messages)

    logger = log.getLogger("init", queue=False)

    used_deprecated_cli_options = []
    for option in DEPRECATED_OPTIONS:
        display_option = option
        if option in cli_options and not cli_options[option] == defaults[option]:
            if option == 'virtType' or option == 'smType':
                display_option = cli_options[option]
            elif any(option in s for s in VIRT_TYPE_OPTIONS):
                display_option = '%s-%s' % (cli_options['virtType'], option)
            elif option in SAT_OPTION_MAP:
                display_option = SAT_OPTION_MAP[option]
            used_deprecated_cli_options.append(display_option)
    deprecated_options_msg = "The following cli options: %s are deprecated and will be removed " \
    "in the next release. Please see 'man virt-who-config' for details on adding a configuration "\
    "section."
    if used_deprecated_cli_options:
        logger.warning(deprecated_options_msg % ', '.join('--' + item for item in used_deprecated_cli_options))

    # Log pending errors
    for err in errors:
        method = getattr(logger, err[0])
        if method is not None and err[0] == 'error':
            method(err[1])

    return logger, effective_config
