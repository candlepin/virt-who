# -*- coding: utf-8 -*-
from __future__ import print_function
"""
For moving variables from system environment to general config file

Copyright (C) 2020 William Poteat <wpoteat@redhat.com>

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

SYSCONFIG_FILENAME = '/etc/sysconfig/virt-who'
GENERAL_CONFIG_FILENAME = '/etc/virt-who.conf'

def main():
    migrate_env_to_config()

def migrate_env_to_config(sysconfig_filename=None, general_config_filename=None):
    if not sysconfig_filename:
        sysconfig_filename = SYSCONFIG_FILENAME
    if not general_config_filename:
        general_config_filename = GENERAL_CONFIG_FILENAME

    interval = None
    debug = None
    one_shot = None

    # read know env variables
    interval = os.environ.get('VIRTWHO_INTERVAL', None)
    debug = os.environ.get('VIRTWHO_DEBUG', None)
    one_shot = os.environ.get('VIRTWHO_ONE_SHOT', None)

    # read the values in the existing /etc/sysconfig/virt-who file
    # these would override the env variables
    env_vars = {}
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

    # read ini file at /etc/virt-who.conf
    lines = []
    if os.path.exists(general_config_filename):
        with open(general_config_filename) as conf:
            lines = conf.readlines()

    output = []
    has_sys_env = False
    has_global = False

    for line in lines:
        if line.startswith('[global]'):
            has_global = True
            output.append(line)
            add_global(output, interval, debug, one_shot)
        elif line.startswith('[system_environment]'):
            has_sys_env = True
            output.append(line)
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

def add_global(output, interval, debug, one_shot):
    if interval:
        output.append("#migrated\ninterval=%s\n" % interval.strip())
    if debug:
        output.append("#migrated\ndebug=%s\n" % ('True' if debug.strip()=='1' else 'False'))
    if one_shot:
        output.append("#migrated\noneshot=%s\n" % ('True' if one_shot.strip()=='1' else 'False'))

def add_system_environment(output, env_vars={}):
    for key, value in env_vars.items():
        if key:
            output.append("#migrated\n%s=%s\n" % (key, value.strip()))

if __name__ == '__main__':
    main()