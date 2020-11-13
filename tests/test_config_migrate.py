# coding=utf-8

"""
Test reading and writing configuration files as well as configuration objects.

Copyright (C) 2014 Radek Novacek <rnovacek@redhat.com>

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
import shutil
import tempfile

from virtwho.migrate.migrateconfiguration import migrate_env_to_config

from base import TestBase, unittest


class TestConfigMigrate(TestBase):

    tmp_config_dir = tempfile.TemporaryDirectory().name
    virt_who_filename = os.path.join(tmp_config_dir, "virt-who")
    virt_who_conf_filename = os.path.join(tmp_config_dir, "virt-who.conf")

    def setUp(self):
        if not os.path.exists(self.tmp_config_dir):
            os.makedirs(self.tmp_config_dir)

    def tearDown(self):
        if os.path.exists(self.tmp_config_dir):
            shutil.rmtree(self.tmp_config_dir)

    def test_migrate_not_existing(self):
        sysconfig =\
"""VIRTWHO_INTERVAL=60
VIRTWHO_DEBUG=1
VIRTWHO_ONE_SHOT=0
HTTPS_PROXY=one
HTTP_PROXY=two
NO_PROXY=*
"""
        expected_conf =\
"""[global]
#migrated
interval=60
#migrated
debug=True
#migrated
oneshot=False

[system_environment]
#migrated
HTTPS_PROXY=one
#migrated
HTTP_PROXY=two
#migrated
NO_PROXY=*
"""

        with open(self.virt_who_filename, "w") as f:
            f.writelines(sysconfig)
        migrate_env_to_config(self.virt_who_filename,
                              self.virt_who_conf_filename)
        with open(self.virt_who_conf_filename, "r") as conf:
            result = conf.readlines()
        self.assertEqual("".join(result), expected_conf)


    def test_migrate_to_existing_no_env(self):
            sysconfig = \
"""VIRTWHO_INTERVAL=60
VIRTWHO_DEBUG=1
VIRTWHO_ONE_SHOT=0
"""
            existing = \
"""[global]
reporter_id=this_one

"""
            expected = \
"""[global]
#migrated
interval=60
#migrated
debug=True
#migrated
oneshot=False
reporter_id=this_one

"""

            with open(self.virt_who_filename, "w") as f:
                f.writelines(sysconfig)
            with open(self.virt_who_conf_filename, "w") as f:
                f.writelines(existing)
            migrate_env_to_config(self.virt_who_filename,
                                  self.virt_who_conf_filename)
            with open(self.virt_who_conf_filename, "r") as conf:
                result = conf.readlines()
            self.assertEqual("".join(result), expected)


    def test_migrate_to_existing(self):
        sysconfig = \
"""VIRTWHO_INTERVAL=60
VIRTWHO_DEBUG=1
VIRTWHO_ONE_SHOT=0
HTTPS_PROXY=one
HTTP_PROXY=two
"""
        existing =\
"""[global]
reporter_id=this_one

[system_environment]
no_proxy=*
"""
        expected =\
"""[global]
#migrated
interval=60
#migrated
debug=True
#migrated
oneshot=False
reporter_id=this_one

[system_environment]
#migrated
HTTPS_PROXY=one
#migrated
HTTP_PROXY=two
no_proxy=*
"""

        with open(self.virt_who_filename, "w") as f:
            f.writelines(sysconfig)
        with open(self.virt_who_conf_filename, "w") as f:
            f.writelines(existing)
        migrate_env_to_config(self.virt_who_filename,
                              self.virt_who_conf_filename)
        with open(self.virt_who_conf_filename, "r") as conf:
            result = conf.readlines()
        self.assertEqual("".join(result), expected)


    def test_migrate_to_existing_entries(self):
        sysconfig = \
"""VIRTWHO_INTERVAL=60
"""
        existing =\
"""[global]
interval=360
reporter_id=this_one

[system_environment]
no_proxy=*
"""
        expected =\
"""[global]
#migrated
interval=60
interval=360
reporter_id=this_one

[system_environment]
no_proxy=*
"""

        with open(self.virt_who_filename, "w") as f:
            f.writelines(sysconfig)
        with open(self.virt_who_conf_filename, "w") as f:
            f.writelines(existing)
        migrate_env_to_config(self.virt_who_filename,
                              self.virt_who_conf_filename)
        with open(self.virt_who_conf_filename, "r") as conf:
            result = conf.readlines()
        self.assertEqual("".join(result), expected)
