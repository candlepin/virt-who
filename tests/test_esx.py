"""
Test of ESX virtualization backend.

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

import logging
import urllib2
import suds
from mock import patch, ANY
from multiprocessing import Queue, Event

from base import TestBase
from config import Config
from virt.esx import Esx
from virt import VirtError


class TestEsx(TestBase):
    def setUp(self):
        config = Config('test', 'esx', 'localhost', 'username', 'password', 'owner', 'env')
        self.esx = Esx(self.logger, config)

    def run_once(self):
        ''' Run ESX in oneshot mode '''
        self.esx._oneshot = True
        self.esx._queue = Queue()
        self.esx._terminate_event = Event()
        self.esx._oneshot = True
        self.esx._interval = 0
        self.esx._run()

    @patch('suds.client.Client')
    def test_connect(self, mock_client):
        mock_client.return_value.service.WaitForUpdatesEx.return_value = None
        self.run_once()

        self.assertTrue(mock_client.called)
        mock_client.assert_called_with(ANY, location="https://localhost/sdk", cache=None, transport=ANY)
        mock_client.service.RetrieveServiceContent.assert_called_once()
        mock_client.service.Login.assert_called_once()

    @patch('suds.client.Client')
    def test_connection_timeout(self, mock_client):
        mock_client.side_effect = urllib2.URLError('timed out')
        self.assertRaises(VirtError, self.run_once)

    @patch('suds.client.Client')
    def test_invalid_login(self, mock_client):
        mock_client.return_value.service.Login.side_effect = suds.WebFault('Permission to perform this operation was denied.', '')
        self.assertRaises(VirtError, self.run_once)

    @patch('suds.client.Client')
    def test_disable_simplified_vim(self, mock_client):
        self.esx.config.esx_simplified_vim = False
        mock_client.return_value.service.RetrievePropertiesEx.return_value = None
        self.run_once()

        self.assertTrue(mock_client.called)
        mock_client.assert_called_with(ANY, location="https://localhost/sdk", transport=ANY)
        mock_client.service.RetrieveServiceContent.assert_called_once()
        mock_client.service.Login.assert_called_once()
