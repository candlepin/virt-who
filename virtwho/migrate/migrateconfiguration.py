# -*- coding: utf-8 -*-
from __future__ import print_function

# For moving variables from system environment to general config file
#
# Copyright (C) 2020 William Poteat <wpoteat@redhat.com>
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
This module is used for merging environment variables (typically defined in
/etc/sysconfig/virt-who) into generic configuration file (typically /etc/virt-who.conf)  
"""

import os

SYSCONFIG_FILENAME = '/etc/sysconfig/virt-who'
GENERAL_CONFIG_FILENAME = '/etc/virt-who.conf'


def main():
    migrate_env_to_config()


def migrate_env_to_config(sysconfig_filename: str = None, general_config_filename: str = None) -> None:
    """
    Try to merge sysconfig file (typically /etc/sysconfig/virt-who) with generic
    virt-who configuration file (typically /etc/virt-who.conf). When sysconfig file
    is not defined, then it tries to read know environment variables: 'VIRTWHO_INTERVAL',
    'VIRTWHO_DEBUG' and 'VIRTWHO_ONE_SHOT'
    @param sysconfig_filename: path to sysconfig file
    @param general_config_filename: path to generic virt-who configuration file
    @return: None
    """

    if not sysconfig_filename:
        sysconfig_filename = SYSCONFIG_FILENAME
    if not general_config_filename:
        general_config_filename = GENERAL_CONFIG_FILENAME

    # read know env variables
    interval = os.environ.get('VIRTWHO_INTERVAL', None)
    debug = os.environ.get('VIRTWHO_DEBUG', None)
    one_shot = os.environ.get('VIRTWHO_ONE_SHOT', None)

    # read the values in the existing /etc/sysconfig/virt-who file
    # these would override the env variables
    env_vars = {}
    if os.path.exists(sysconfig_filename):
        with open(sysconfig_filename) as myfile:
            for line in myfile:
                if not line.startswith('#'):
                    name, var = line.partition("=")[::2]
                    env_vars[name.strip()] = var

    # pop is used because these values in the global
    # section. The remaining values will go into
    # the system_environment section.
    if 'VIRTWHO_INTERVAL' in env_vars:
        interval = env_vars.pop('VIRTWHO_INTERVAL')
    if 'VIRTWHO_DEBUG' in env_vars:
        debug = env_vars.pop('VIRTWHO_DEBUG')
    if 'VIRTWHO_ONE_SHOT' in env_vars:
        one_shot = env_vars.pop('VIRTWHO_ONE_SHOT')

    # When there is no environment variable or anything defined in sysconfig file, then
    # there is also no need to merge anything to virt-who.conf file, and we can end here
    if interval is None and debug is None and one_shot is None and len(env_vars) == 0:
        return

    # read ini file at /etc/virt-who.conf
    lines = []
    if os.path.exists(general_config_filename):
        with open(general_config_filename) as conf:
            lines = conf.readlines()

    output = []
    has_sys_env = False
    has_global = False

    for line in lines:
        stripped = line.strip()
        if stripped == '[global]' or (
            stripped.startswith('#') and stripped[1:].strip() == '[global]'
        ):
            has_global = True
            output.append('[global]\n')
            add_global(output, interval, debug, one_shot)
        elif stripped == '[system_environment]' or (
            stripped.startswith('#') and stripped[1:].strip() == '[system_environment]'
        ):
            has_sys_env = True
            output.append('[system_environment]\n')
            add_system_environment(output, env_vars)
        else:
            output.append(line)

    if not has_global:
        if interval or debug or one_shot:
            if len(output) != 0:
                output.append('\n')
            output.append('[global]\n')
            add_global(output, interval, debug, one_shot)

    if not has_sys_env:
        if len(env_vars) > 0:
            if len(output) != 0:
                output.append('\n')
            output.append('[system_environment]\n')
            add_system_environment(output, env_vars)

    # write /etc/virt-who.conf
    with open(general_config_filename, "w") as conf:
        conf.writelines(output)


def add_global(output: list, interval: str, debug: str, one_shot: str) -> None:
    """
    Add some options to [global] section with comment that this
    option was migrated
    @param output: list of lines to be added to final configuration file
    @param interval: value of interval option
    @param debug: value of debug option
    @param one_shot: value of one_shot option
    @return: None
    """
    if interval:
        output.append("#migrated\ninterval=%s\n" % interval.strip())
    if debug:
        output.append("#migrated\ndebug=%s\n" % ('True' if debug.strip() == '1' else 'False'))
    if one_shot:
        output.append("#migrated\noneshot=%s\n" % ('True' if one_shot.strip() == '1' else 'False'))


def add_system_environment(output: list, env_vars: dict = None) -> None:
    """
    Add other environment variables defined in sysconfig file to [system_environment] section
    @param output: list of lines to be added to final configuration file
    @param env_vars: dictionary with other environment variables defined in sysconfig file
    @return: None
    """
    if env_vars is None:
        return
    for key, value in env_vars.items():
        if key:
            output.append("#migrated\n%s=%s\n" % (key, value.strip()))


if __name__ == '__main__':
    main()
