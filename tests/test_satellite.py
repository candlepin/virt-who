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

import threading
import tempfile
import pickle
import shutil
import xmlrpclib
from SimpleXMLRPCServer import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from binascii import hexlify
from mock import MagicMock, patch

from base import TestBase

from virtwho.config import DestinationToSourceMapper, VW_ENV_CLI_SECTION_NAME, EffectiveConfig, ConfigSection,\
    parse_file
from virtwho.manager import Manager
from virtwho.manager.satellite import Satellite, SatelliteError
from virtwho.virt import Guest, Hypervisor, HostGuestAssociationReport
from virtwho.parser import parse_options
from virtwho import password


TEST_SYSTEM_ID = 'test-system-id'
TEST_PORT = 8090


class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/XMLRPC', '/rpc/api')


class FakeSatellite(SimpleXMLRPCServer):
    AUTH_TOKEN = 'This is auth session'

    def __init__(self):
        SimpleXMLRPCServer.__init__(self, ("localhost", TEST_PORT), requestHandler=RequestHandler)
        # /XMLRPC interface
        self.register_function(self.new_system_user_pass, "registration.new_system_user_pass")
        self.register_function(self.refresh_hw_profile, "registration.refresh_hw_profile")
        self.register_function(self.virt_notify, "registration.virt_notify")
        # /xml/api interface
        self.register_function(self.auth_login, "auth.login")
        self.register_function(self.get_channel_details, "channel.software.getDetails")
        self.register_function(self.create_channel, "channel.software.create")
        self.register_function(self.set_map_for_org, "distchannel.setMapForOrg")
        self.register_function(self.get_user_details, "user.getDetails")

        self.channel_created = False
        self.created_system = None

    def new_system_user_pass(self, profile_name, os_release_name, version, arch, username, password, options):
        if username != "username":
            raise Exception("Wrong username")
        if password != "password":
            raise Exception("Wrong password")
        self.created_system = {
            'profile_name': profile_name,
            'os_release_name': os_release_name,
            'version': version,
            'arch': arch,
            'username': username,
            'password': password,
            'options': options,
        }
        return {'system_id': TEST_SYSTEM_ID}

    def refresh_hw_profile(self, system_id, profile):
        if system_id != TEST_SYSTEM_ID:
            raise Exception("Wrong system id")
        return ""

    def virt_notify(self, system_id, plan):
        if system_id != TEST_SYSTEM_ID:
            raise xmlrpclib.Fault(-9, "Wrong system id")

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

    def auth_login(self, username, password):
        return self.AUTH_TOKEN

    def get_channel_details(self, session, channelLabel):
        assert session == self.AUTH_TOKEN
        if self.channel_created:
            return {
                'id': 42
            }
        else:
            raise xmlrpclib.Fault(faultCode=-210, faultString='Not found')

    def create_channel(self, session, label, name, summary, archLabel, parentLabel):
        assert session == self.AUTH_TOKEN
        self.channel_created = True
        return 1

    def set_map_for_org(self, session, os, release, archName, channelLabel):
        assert session == self.AUTH_TOKEN
        return 1

    def get_user_details(self, session, login):
        assert session == self.AUTH_TOKEN
        return dict(org_id=101)

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
                Guest('guest1-1', xvirt.CONFIG_TYPE, Guest.STATE_RUNNING),
                Guest('guest1-2', xvirt.CONFIG_TYPE, Guest.STATE_SHUTOFF)
            ]),
            Hypervisor('host-2', [
                Guest('guest2-1', xvirt.CONFIG_TYPE, Guest.STATE_RUNNING),
                Guest('guest2-2', xvirt.CONFIG_TYPE, Guest.STATE_SHUTOFF),
                Guest('guest2-3', xvirt.CONFIG_TYPE, Guest.STATE_RUNNING)
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
        config = Config('test', 'libvirt')
        report = HostGuestAssociationReport(config, self.mapping)
        self.assertRaises(SatelliteError, s.hypervisorCheckIn, report, options)

    def test_wrong_username(self):
        options = Options("http://localhost:%s" % TEST_PORT, "wrong", "password")
        options.force_register = True
        s = Satellite(self.logger, options)
        config = Config('test', 'libvirt')
        report = HostGuestAssociationReport(config, self.mapping)
        self.assertRaises(SatelliteError, s.hypervisorCheckIn, report, options)

    def test_wrong_password(self):
        options = Options("http://localhost:%s" % TEST_PORT, "username", "wrong")
        options.force_register = True
        s = Satellite(self.logger, options)
        config = Config('test', 'libvirt')
        report = HostGuestAssociationReport(config, self.mapping)
        self.assertRaises(SatelliteError, s.hypervisorCheckIn, report, options)

    def test_new_system(self):
        options = Options("http://localhost:%s" % TEST_PORT, "username", "password")
        options.force_register = True
        s = Satellite(self.logger, options)

        config = Config('test', 'libvirt')
        report = HostGuestAssociationReport(config, self.mapping)
        s.hypervisorCheckIn(report, options)

    def test_hypervisorCheckIn(self):
        options = Options("http://localhost:%s" % TEST_PORT, "username", "password")
        options.force_register = True
        s = Satellite(self.logger, options)

        config = Config('test', 'libvirt')
        report = HostGuestAssociationReport(config, self.mapping)
        result = s.hypervisorCheckIn(report, options)
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
        s = Satellite(self.logger, options)

        s.HYPERVISOR_SYSTEMID_FILE = filename.replace(TEST_SYSTEM_ID, '%s')

        config = Config('test', 'libvirt')
        report = HostGuestAssociationReport(config, self.mapping)
        result = s.hypervisorCheckIn(report, options)
        self.assertTrue("failedUpdate" in result)
        self.assertTrue("created" in result)
        self.assertTrue("updated" in result)

    def test_hypervisorCheckIn_deleted(self):
        '''Test running hypervisorCheckIn on system that was deleted from Satellite'''
        system_id = 'wrong-system-id'
        temp, filename = tempfile.mkstemp(suffix=system_id)
        self.addCleanup(os.unlink, filename)
        with os.fdopen(temp, "wb") as f:
            pickle.dump({'system_id': system_id}, f)

        options = Options("http://localhost:%s" % TEST_PORT, "username", "password")
        s = Satellite(self.logger, options)

        s.HYPERVISOR_SYSTEMID_FILE = filename.replace(system_id, '%s')
        config = Config('test', 'libvirt')
        mapping = {
            'hypervisors': [
                Hypervisor(system_id, [])
            ]
        }
        report = HostGuestAssociationReport(config, mapping)
        s.hypervisorCheckIn(report, options)
        with open(filename, "rb") as f:
            data = pickle.load(f)
        self.assertEqual(data['system_id'], TEST_SYSTEM_ID)

    def test_creating_channel(self):
        options = Options("http://localhost:%s" % TEST_PORT, "username", "password")
        options.force_register = True
        s = Satellite(self.logger, options)

        config = Config('test', 'libvirt')
        report = HostGuestAssociationReport(config, self.mapping)
        result = s.hypervisorCheckIn(report, options)
        self.assertTrue(self.fake_server.channel_created)
        self.assertIsNotNone(self.fake_server.created_system)
        self.assertTrue("created" in result)

    def test_using_existing_channel(self):
        options = Options("http://localhost:%s" % TEST_PORT, "username", "password")
        options.force_register = True
        s = Satellite(self.logger, options)
        self.fake_server.channel_created = True

        config = Config('test', 'libvirt')
        report = HostGuestAssociationReport(config, self.mapping)
        result = s.hypervisorCheckIn(report, options)
        self.assertTrue(self.fake_server.channel_created)
        self.assertIsNotNone(self.fake_server.created_system)
        self.assertTrue("created" in result)

    def test_per_config_options(self):
        options = Options(None, None, None)
        options.force_register = True
        config = Config('test', 'libvirt', sat_server="http://localhost:%s" % TEST_PORT, sat_username='username', sat_password='password')
        s = Satellite(self.logger, options)

        report = HostGuestAssociationReport(config, self.mapping)
        result = s.hypervisorCheckIn(report, options)
        self.assertTrue("failedUpdate" in result)
        self.assertTrue("created" in result)
        self.assertTrue("updated" in result)

    @patch('virtwho.password.Password._can_write')
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
            report = HostGuestAssociationReport(config, self.mapping)
            result = s.hypervisorCheckIn(report, options)
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
        logger, config = parse_options()
        options = config[VW_ENV_CLI_SECTION_NAME]
        manager = Manager.fromOptions(logger, options)
        self.assertTrue(isinstance(manager, Satellite))

    def test_satellite_config_cmd(self):
        os.environ = {}
        sys.argv = ["virt-who", "--satellite",
                    "--satellite-server=sat.example.com",
                    "--satellite-username=username",
                    "--satellite-password=password",
                    "--libvirt"]
        logger, config = parse_options()
        options = config[VW_ENV_CLI_SECTION_NAME]
        manager = Manager.fromOptions(logger, options)
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
        conf = parse_file(os.path.join(config_dir, "test.conf"))
        effective_config = EffectiveConfig()
        conf_values = conf.pop("test")
        effective_config["test"] = ConfigSection.from_dict(
            conf_values,
            "test",
            effective_config
        )
        config_manager = DestinationToSourceMapper(effective_config)
        self.assertEqual(len(config_manager.configs), 1)
        options = dict(config_manager.configs)["test"]
        print(options)
        manager = Manager.fromOptions(self.logger, options)
        self.assertTrue(isinstance(manager, Satellite))
        self.assertEqual(options['sat_server'], 'sat.example.com')
