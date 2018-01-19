"""
Test of VDSM virtualization backend.

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

from mock import MagicMock

from base import TestBase

from virtwho.virt.vdsm import Vdsm
from virtwho.virt.vdsm.vdsm import VdsmConfigSection
from virtwho.virt.virt import Guest


class TestVdsm(TestBase):

    def create_config(self, name, wrapper, **kwargs):
        config = VdsmConfigSection(name, wrapper)
        config.update(**kwargs)
        config.validate()
        return config

    def setUp(self):
        config = self.create_config('test', None, type='vdsm')

        def fake_secure_connect(self):
            return MagicMock()

        Vdsm._secure_connect = fake_secure_connect
        self.vdsm = Vdsm(self.logger, config, None)
        self.vdsm.prepare()

    def test_connect(self):
        self.vdsm.server.list = MagicMock()
        self.vdsm.server.list.return_value = {
            'status': {
                'code': 0
            },
            'vmList': [
                {
                    'vmId': '1',
                    'status': 'Down'
                }, {
                    'vmId': '2',
                    'status': 'Up'
                }, {
                    'vmId': '3',
                    'status': 'Up'
                }
            ]
        }
        domains = self.vdsm.listDomains()
        self.assertEquals([d.uuid for d in domains], ['1', '2', '3'])
        self.assertEquals([d.state for d in domains], [Guest.STATE_SHUTOFF, Guest.STATE_RUNNING, Guest.STATE_RUNNING])
        self.assertEqual([d.virtWhoType for d in domains], ['vdsm', 'vdsm', 'vdsm'])
        self.vdsm.server.list.assert_called_once_with(True)
