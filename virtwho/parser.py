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
import six

from argparse import ArgumentParser, Action

from virtwho import log, MinimumSendInterval, DefaultInterval, SAT5, SAT6
from virtwho.config import NotSetSentinel, init_config, DEFAULTS, VW_GLOBAL,\
    VW_ENV_CLI_SECTION_NAME
from virtwho.virt.virt import Virt


# List of supported virtualization backends
VIRT_BACKENDS = Virt.hypervisor_types()

SAT5_VM_DISPATCHER = {
    'libvirt': {'owner': False, 'server': False, 'username': False},
    'esx': {'owner': False, 'server': True, 'username': True},
    'xen': {'owner': False, 'server': True, 'username': True},
    'rhevm': {'owner': False, 'server': True, 'username': True},
    'hyperv': {'owner': False, 'server': True, 'username': True},
    'kubevirt': {'owner': False, 'server': False, 'username': False, 'kubeconfig': True, 'kubeversion': False},
    'ahv' : {'owner': False, 'server': False, 'username': False},
}

SAT6_VM_DISPATCHER = {
    'libvirt': {'owner': False, 'server': False, 'username': False},
    'esx': {'owner': True, 'server': True, 'username': True},
    'xen': {'owner': True, 'server': True, 'username': True},
    'rhevm': {'owner': True, 'server': True, 'username': True},
    'hyperv': {'owner': True, 'server': True, 'username': True},
    'kubevirt': {'owner': True, 'server': False, 'username': False, 'kubeconfig': True, 'kubeversion': False},
    'ahv' : {'owner': False, 'server': False, 'username': False},
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
        virtualization backend [--libvirt|--esx|--rhevm|--hyperv|--xen|--kubevirt|--ahv]
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
        "VIRTWHO_ONE_SHOT": ("oneshot",
                             store_const,
                             "true"),
        "VIRTWHO_SAM": ("sm_type", store_const, SAT6),
        "VIRTWHO_SATELLITE6": ("sm_type", store_const, SAT6),
        "VIRTWHO_SATELLITE5": ("sm_type", store_const, SAT5),
        "VIRTWHO_SATELLITE": ("sm_type", store_const, SAT5),
        "VIRTWHO_LIBVIRT": ("virt_type", store_const, "libvirt"),
        "VIRTWHO_ESX": ("virt_type", store_const, "esx"),
        "VIRTWHO_XEN": ("virt_type", store_const, "xen"),
        "VIRTWHO_RHEVM": ("virt_type", store_const, "rhevm"),
        "VIRTWHO_HYPERV": ("virt_type", store_const, "hyperv"),
        "VIRTWHO_KUBEVIRT": ("virt_type", store_const, "kubevirt"),
        "VIRTWHO_AHV": ("virt_type", store_const, "ahv"),
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

        keys = ['owner', 'server', 'username','password']
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
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),'version.py')
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
    if six.PY2:
        parser = ArgumentParser(
            usage="virt-who [-d] [-o] [-i INTERVAL] [-p] [-c CONFIGS] [--version] "
                  "[-m] [-l LOG_DIR] [-f LOG_FILE] [-r REPORTER_ID] [--sam|--satellite5|--satellite6] "
                  "[--libvirt|--esx|--rhevm|--hyperv|--xen|--kubevirt|--ahv]",
            description="Agent for reporting virtual guest IDs to subscription manager",
            epilog="virt-who also reads environment variables. They have the same name as "
                   "command line arguments but uppercased, with underscore instead of dash "
                   "and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are "
                   "considered as disabled, non-empty as enabled."
        )
    if six.PY3:
        parser = ArgumentParser(
            usage="virt-who [-d] [-o] [-i INTERVAL] [-p] [-c CONFIGS] [--version]",
            description="Agent for reporting virtual guest IDs to subscription manager",
            epilog = "virt-who also reads environment variables. They have the same name as "
                  "command line arguments but uppercased, with underscore instead of dash "
                  "and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are "
                  "considered as disabled, non-empty as enabled."
        )
    parser.add_argument("-d", "--debug", action="store_true", dest="debug", default=False,
                        help="Enable debugging output")
    parser.add_argument("-o", "--one-shot", action="store_true", dest="oneshot", default=False,
                        help="Send the list of guest IDs and exit immediately")
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
    if six.PY2:
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
        virt_group.add_argument("--libvirt", action=StoreVirtType, dest="virt_type", const="libvirt",
                                default=None, help="[Deprecated] Use libvirt to list virtual guests")
        virt_group.add_argument("--esx", action=StoreVirtType, dest="virt_type", const="esx",
                                help="[Deprecated] Register ESX machines using vCenter")
        virt_group.add_argument("--xen", action=StoreVirtType, dest="virt_type", const="xen",
                                help="[Deprecated] Register XEN machines using XenServer")
        virt_group.add_argument("--rhevm", action=StoreVirtType, dest="virt_type", const="rhevm",
                                help="[Deprecated] Register guests using RHEV-M")
        virt_group.add_argument("--hyperv", action=StoreVirtType, dest="virt_type", const="hyperv",
                                help="[Deprecated] Register guests using Hyper-V")
        virt_group.add_argument("--kubevirt", action=StoreVirtType, dest="virt_type", const="kubevirt",
                                help="[Deprecated] Register guests using Kubevirt")
        virt_group.add_argument("--ahv", action=StoreVirtType, dest="virt_type", const="ahv",
                                default=None, help="[Deprecated] Register Acropolis vms using AHV.")

        manager_group = parser.add_argument_group(
            title="Subscription manager",
            description="Choose where the host/guest associations should be reported"
        )
        manager_group.add_argument("--sam", action="store_const", dest="sm_type", const=SAT6, default=SAT6,
                                   help="[Deprecated] Report host/guest associations to the Subscription Asset Manager, "
                                   "Satellite 6, or Red Hat Subscription Management (RHSM). "
                                   "This option specifies the default behaviour, and thus it is not used [default]")
        manager_group.add_argument("--satellite6", action="store_const", dest="sm_type", const=SAT6,
                                   help="[Deprecated] Report host/guest associations to the Subscription Asset Manager, "
                                   "Satellite 6, or Red Hat Subscription Management (RHSM)."
                                   "This option specifies the default behaviour, and thus it is not used [default]")
        manager_group.add_argument("--satellite5", action="store_const", dest="sm_type", const=SAT5,
                                   help="[Deprecated] Report host/guest associations to the Satellite 5 server")
        manager_group.add_argument("--satellite", action="store_const", dest="sm_type", const=SAT5)

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

        kubevirt_group = parser.add_argument_group(
            title="Kubevirt options",
            description="Use these options with --kubevirt"
        )
        kubevirt_group.add_argument("--kubevirt-owner", action=StoreGroupArgument, dest="owner", default="",
                                    help="[Deprecated] Organization who has purchased subscriptions of the products")
        kubevirt_group.add_argument("--kubevirt-env", action=StoreGroupArgument, dest="env", default="",
                                    help="[Deprecated] Environment where Kubevirt belongs to")
        kubevirt_group.add_argument("--kubevirt-cfg", action=StoreGroupArgument, dest="kubeconfig", default="~/.kube/config",
                                    help="[Deprecated] Path to Kubernetes config file")

        ahv_group = parser.add_argument_group(
            title="AHV PC/PE options",
            description="Use these options with --ahv"
        )
        ahv_group.add_argument("--ahv-owner", action=StoreGroupArgument, dest="owner", default="",
                               help="[Deprecated] Organization who has purchased subscriptions of the products")
        ahv_group.add_argument("--ahv-env", action=StoreGroupArgument, dest="env", default="",
                               help="[Deprecated] Environment where the vCenter server belongs to")
        ahv_group.add_argument("--ahv-server", action=StoreGroupArgument,
                               dest="server", default="",
                               help="[Deprecated] URL of the ahv server to connect to")
        ahv_group.add_argument("--ahv-username", action=StoreGroupArgument,
                               dest="username", default="",
                               help="[Deprecated] Username for connecting to ahv server")
        ahv_group.add_argument("--ahv-password", action=StoreGroupArgument,
                               dest="password", default="",
                               help="[Deprecated] Password for connecting to ahv server")
        ahv_group.add_argument("--pc-server", action=StoreGroupArgument, dest="server", default="",
                               help="[Deprecated] URL of the PC server to connect to")
        ahv_group.add_argument("--pc-username", action=StoreGroupArgument, dest="username", default="",
                               help="[Deprecated] Username for connecting to PC")
        ahv_group.add_argument("--pc-password", action=StoreGroupArgument, dest="password", default="",
                               help="[Deprecated] Password for connecting to PC")

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
    SAT_OPTION_MAP = {'sat_server':'satellite-server', 'sat_username':'satellite-username', 'sat_password':'satellite-password'}

    # Read command line arguments first
    cli_options, errors, defaults = parse_cli_arguments()

    if 'version' in cli_options and cli_options['version']:
        print(get_version())
        exit(os.EX_OK)

    # Read configuration env. variables
    env_options = read_config_env_variables()

    if six.PY2:
        # Read environments variables for virtualization backends
        env_options, env_errors = read_vm_backend_env_variables(env_options)
        errors.extend(env_errors)

    # Create the effective config that virt-who will use to run
    effective_config = init_config(env_options, cli_options)
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
