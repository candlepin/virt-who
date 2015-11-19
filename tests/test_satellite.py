"""
Test for Satellite module, part of virt-who

Copyright (C) 2013 Radek Novacek <rnovacek@redhat.com>

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
import sys

from base import TestBase

import logging
import threading
import tempfile
import pickle
import shutil
from SimpleXMLRPCServer import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler

from mock import MagicMock, patch, ANY

from config import Config, ConfigManager
from manager import Manager
from manager.satellite import Satellite, SatelliteError
from virt import Guest, Hypervisor
from virtwho import parseOptions
import password
from binascii import hexlify


TEST_SYSTEM_ID = 'test-system-id'
TEST_PORT = 8090


class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/XMLRPC',)


class FakeSatellite(SimpleXMLRPCServer):
    def __init__(self):
        SimpleXMLRPCServer.__init__(self, ("localhost", TEST_PORT), requestHandler=RequestHandler)
        self.register_function(self.new_system_user_pass, "registration.new_system_user_pass")
        self.register_function(self.refresh_hw_profile, "registration.refresh_hw_profile")
        self.register_function(self.virt_notify, "registration.virt_notify")

    def new_system_user_pass(self, profile_name, os_release_name, version, arch, username, password, options):
        if username != "username":
            raise Exception("Wrong username")
        if password != "password":
            raise Exception("Wrong password")
        return {'system_id': TEST_SYSTEM_ID}

    def refresh_hw_profile(self, system_id, profile):
        if system_id != TEST_SYSTEM_ID:
            raise Exception("Wrong system id")
        return ""

    def virt_notify(self, system_id, plan):
        if system_id != TEST_SYSTEM_ID:
            raise Exception("Wrong system id")

        if plan[0] != [0, 'exists', 'system', {'uuid': '0000000000000000', 'identity': 'host'}]:
            raise Exception("Wrong value for virt_notify: invalid format of first entry")
        if plan[1] != [0, 'crawl_began', 'system', {}]:
            raise Exception("Wrong value for virt_notify: invalid format of second entry")
        if plan[-1] != [0, 'crawl_ended', 'system', {}]:
            raise Exception("Wrong value for virt_notify: invalid format of last entry")
        for item in plan[2:-1]:
            if item[0] != 0:
                raise Exception("Wrong value for virt_notify: invalid format first item of an entry")
            if item[1] != 'exists':
                raise Exception("Wrong value for virt_notify: invalid format second item of an entry")
            if item[2] != 'domain':
                raise Exception("Wrong value for virt_notify: invalid format third item of an entry")
            if not item[3]['uuid'].startswith("guest"):
                raise Exception("Wrong value for virt_notify: invalid format uuid item")
        return 0


class Options(object):
    def __init__(self, server, username, password):
        self.sat_server = server
        self.sat_username = username
        self.sat_password = password


xvirt = type("", (), {'CONFIG_TYPE': 'xxx'})()


class TestSatellite(TestBase):
    mapping = {
        'hypervisors': [
            Hypervisor('host-1', [
                Guest('guest1-1', xvirt, Guest.STATE_RUNNING),
                Guest('guest1-2', xvirt, Guest.STATE_SHUTOFF)
            ]),
            Hypervisor('host-2', [
                Guest('guest2-1', xvirt, Guest.STATE_RUNNING),
                Guest('guest2-2', xvirt, Guest.STATE_SHUTOFF),
                Guest('guest2-3', xvirt, Guest.STATE_RUNNING)
            ])
        ]
    }

    @classmethod
    def setUpClass(cls):
        super(TestSatellite, cls).setUpClass()
        cls.fake_server = FakeSatellite()
        cls.thread = threading.Thread(target=cls.fake_server.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake_server.shutdown()

    def test_wrong_server(self):
        options = Options("wrong_server", "abc", "def")
        s = Satellite(self.logger, options)
        #self.assertRaises(SatelliteError, s.connect, "wrong_server", "abc", "def")
        options.env = "ENV"
        options.owner = "OWNER"

        s.hypervisorCheckIn(options, {'hypervisors': []}, "test")
        #self.assertRaises(SatelliteError, s.connect, "localhost", "abc", "def")

    def test_new_system(self):
        options = Options("http://localhost:%s" % TEST_PORT, "username", "password")
        options.force_register = True
        s = Satellite(self.logger, options)

        # Register with wrong username
        #self.assertRaises(SatelliteError, s.connect, "http://localhost:8080", "wrong", "password", force_register=True)

        # Register with wrong password
        #self.assertRaises(SatelliteError, s.connect, "http://localhost:8080", "username", "wrong", force_register=True)

    def test_hypervisorCheckIn(self):
        options = Options("http://localhost:%s" % TEST_PORT, "username", "password")
        options.force_register = True
        options.env = "ENV"
        options.owner = "OWNER"
        s = Satellite(self.logger, options)

        result = s.hypervisorCheckIn(options, self.mapping, "type")
        self.assertTrue("failedUpdate" in result)
        self.assertTrue("created" in result)
        self.assertTrue("updated" in result)

    def test_hypervisorCheckIn_preregistered(self):
        temp, filename = tempfile.mkstemp(suffix=TEST_SYSTEM_ID)
        self.addCleanup(os.unlink, filename)
        f = os.fdopen(temp, "wb")
        pickle.dump({'system_id': TEST_SYSTEM_ID}, f)
        f.close()

        options = Options("http://localhost:%s" % TEST_PORT, "username", "password")
        options.env = "ENV"
        options.owner = "OWNER"
        s = Satellite(self.logger, options)

        s.HYPERVISOR_SYSTEMID_FILE = filename.replace(TEST_SYSTEM_ID, '%s')

        result = s.hypervisorCheckIn(options, self.mapping, "type")
        self.assertTrue("failedUpdate" in result)
        self.assertTrue("created" in result)
        self.assertTrue("updated" in result)

    def test_per_config_options(self):
        options = Options(None, None, None)
        options.force_register = True
        config = Config('test', 'libvirt', sat_server="http://localhost:%s" % TEST_PORT, sat_username='username', sat_password='password')
        s = Satellite(self.logger, options)
        result = s.hypervisorCheckIn(config, self.mapping, "type")
        self.assertTrue("failedUpdate" in result)
        self.assertTrue("created" in result)
        self.assertTrue("updated" in result)

    @patch('password.Password._can_write')
    def test_per_config_options_encrypted(self, can_write):
        options = Options(None, None, None)
        options.force_register = True
        can_write.return_value = True
        with tempfile.NamedTemporaryFile() as tmp:
            password.Password.KEYFILE = tmp.name
            config = Config('test', 'libvirt',
                            sat_server="http://localhost:%s" % TEST_PORT,
                            sat_username='username',
                            sat_encrypted_password=hexlify(password.Password.encrypt('password')))
            s = Manager.fromOptions(self.logger, options, config)
            self.assertTrue(isinstance(s, Satellite))
            result = s.hypervisorCheckIn(config, self.mapping, "type")
        self.assertTrue("failedUpdate" in result)
        self.assertTrue("created" in result)
        self.assertTrue("updated" in result)


class TestSatelliteConfig(TestBase):
    def test_satellite_config_env(self):
        os.environ = {
            "VIRTWHO_SATELLITE": '1',
            "VIRTWHO_SATELLITE_SERVER": 'sat.example.com',
            "VIRTWHO_SATELLITE_USERNAME": 'username',
            "VIRTWHO_SATELLITE_PASSWORD": 'password',
            "VIRTWHO_LIBVIRT": '1'
        }
        sys.argv = ["virt-who"]
        logger, options = parseOptions()
        config = Config("env/cmdline", options.virtType, defaults={}, **options)
        config.checkOptions(logger)
        manager = Manager.fromOptions(logger, options, config)
        self.assertTrue(isinstance(manager, Satellite))

    def test_satellite_config_cmd(self):
        os.environ = {}
        sys.argv = ["virt-who", "--satellite",
                    "--satellite-server=sat.example.com",
                    "--satellite-username=username",
                    "--satellite-password=password",
                    "--libvirt"]
        logger, options = parseOptions()
        config = Config("env/cmdline", options.virtType, defaults={}, **options)
        config.checkOptions(logger)
        manager = Manager.fromOptions(logger, options, config)
        self.assertTrue(isinstance(manager, Satellite))

    def test_satellite_config_file(self):
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=libvirt
sat_server=sat.example.com
""")

        config_manager = ConfigManager(self.logger, config_dir)
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0]
        manager = Manager.fromOptions(self.logger, MagicMock(), config)
        self.assertTrue(isinstance(manager, Satellite))
        self.assertEqual(config.sat_server, 'sat.example.com')


if __name__ == '__main__':
    unittest.main()
