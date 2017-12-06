from __future__ import print_function
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

from mock import MagicMock, patch
from unittest import TestCase

from base import TestBase

from virtwho.virt.vdsm import Vdsm
from virtwho.virt.vdsm.jsonrpc import JsonRpcClient
from virtwho.virt.vdsm.stomp import StompFrame, StompClient
from virtwho.virt.vdsm.vdsm import VdsmConfigSection
from virtwho.virt.virt import Guest

import json


class TestVdsm(TestBase):

    def create_config(self, name, wrapper, **kwargs):
        config = VdsmConfigSection(name, wrapper)
        config.update(**kwargs)
        config.validate()
        return config

    def setUp(self):
        config = self.create_config('test', None, type='vdsm')
        Vdsm._create_ssl_context = MagicMock()
        self.vdsm = Vdsm(self.logger, config, None)
        self.mock_jsonrpc_client = MagicMock()
        mock_jsonrpc_client_factory = MagicMock(return_value=self.mock_jsonrpc_client)

        self.patch_jsonrpc_client = patch('virtwho.virt.vdsm.vdsm.JsonRpcClient', mock_jsonrpc_client_factory)
        self.patch_xmlrpclib = patch('virtwho.virt.vdsm.vdsm.xmlrpc_client', MagicMock())
        self.patch_jsonrpc_client.start()
        self.patch_xmlrpclib.start()

    def tearDown(self):
        self.patch_jsonrpc_client.stop()
        self.patch_xmlrpclib.stop()

    def test_connect_via_xmlrpc(self):
        self.mock_jsonrpc_client.connect = MagicMock(side_effect=IOError)
        self.vdsm.prepare()
        self.assertIsNone(self.vdsm.jsonrpc_client)
        self.assertIsNotNone(self.vdsm.xmlrpc_client)
        self.vdsm.xmlrpc_client.list = MagicMock()
        self.vdsm.xmlrpc_client.list.return_value = {
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
        self.assertIsNone(self.vdsm.jsonrpc_client)
        self.assertEquals([d.uuid for d in domains], ['1', '2', '3'])
        self.assertEquals([d.state for d in domains], [Guest.STATE_SHUTOFF, Guest.STATE_RUNNING, Guest.STATE_RUNNING])
        self.assertEqual([d.virtWhoType for d in domains], ['vdsm', 'vdsm', 'vdsm'])
        self.vdsm.xmlrpc_client.list.assert_called_once_with(True)

    def test_connect_via_jsonrpc(self):
        self.mock_jsonrpc_client.connect = MagicMock()
        self.vdsm.prepare()
        self.assertIsNotNone(self.vdsm.jsonrpc_client)
        self.assertIsNone(self.vdsm.xmlrpc_client)
        self.vdsm.jsonrpc_client.call = MagicMock()
        self.vdsm.jsonrpc_client.call.return_value = [
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
        domains = self.vdsm.listDomains()
        self.assertIsNone(self.vdsm.xmlrpc_client)
        self.assertEquals([d.uuid for d in domains], ['1', '2', '3'])
        self.assertEquals([d.state for d in domains], [Guest.STATE_SHUTOFF, Guest.STATE_RUNNING, Guest.STATE_RUNNING])
        self.assertEqual([d.virtWhoType for d in domains], ['vdsm', 'vdsm', 'vdsm'])
        self.vdsm.jsonrpc_client.call.assert_called_once_with('Host.getVMList', onlyUUID=False)


class TestStomp(TestCase):
    def test_stomp_message_encoding_with_headers_without_body(self):
        connect_message = StompFrame(u'CONNECT', headers={
           u'accept-version': u'1.2',
           u'host': u'localhost',
        })
        result = connect_message.to_bytes()
        self.assertEqual(b'CONNECT\naccept-version:1.2\nhost:localhost\n\n\x00', result)

    def test_stomp_message_encoding_with_headers_with_body(self):
        connect_message = StompFrame(u'CONNECT', headers={
           u'accept-version': u'1.2',
           u'host': u'localhost',
        }, body=b'extra')
        result = connect_message.to_bytes()
        self.assertEqual(b'CONNECT\naccept-version:1.2\nhost:localhost\n\nextra\x00', result)

    def test_stomp_message_encoding_without_headers_without_body(self):
        connect_message = StompFrame(u'CONNECT')
        result = connect_message.to_bytes()
        self.assertEqual(b'CONNECT\n\n\x00', result)

    def test_stomp_message_encoding_without_headers_with_body(self):
        connect_message = StompFrame(u'CONNECT', body=b'test')
        result = connect_message.to_bytes()
        self.assertEqual(b'CONNECT\n\ntest\x00', result)

    def test_stomp_message_decoding_without_body(self):
        data = b'CONNECT\naccept-version:1.2\nhost:localhost\n\n\x00'
        connect_message = StompFrame.from_bytes(data)
        self.assertEqual(u'CONNECT', connect_message.command)
        self.assertEqual({
           u'accept-version': u'1.2',
           u'host': u'localhost',
        }, connect_message.headers)
        self.assertEqual(connect_message.body, b'')

    def test_stomp_message_decoding_with_headers_with_body(self):
        data = b'CONNECT\naccept-version:1.2\n\nlalala\x00'
        connect_message = StompFrame.from_bytes(data)
        self.assertEqual(u'CONNECT', connect_message.command)
        self.assertEqual({
            u'accept-version': u'1.2',
        }, connect_message.headers)
        self.assertEqual(connect_message.body, b'lalala')

    def test_stomp_message_decoding_without_headers_with_body(self):
        data = b'CONNECT\n\nlalala\x00'
        connect_message = StompFrame.from_bytes(data)
        self.assertEqual(u'CONNECT', connect_message.command)
        self.assertEqual({}, connect_message.headers)
        self.assertEqual(connect_message.body, b'lalala')

    def test_stomp_message_decoding_without_headers_without_body(self):
        data = b'CONNECT\n\n\x00'
        connect_message = StompFrame.from_bytes(data)
        self.assertEqual(u'CONNECT', connect_message.command)
        self.assertEqual({}, connect_message.headers)
        self.assertEqual(connect_message.body, b'')


class StompClientTest(TestCase):
    def test_stomp_client_connect_sends_connect_frame(self):
        with patch('socket.socket') as socket_factory:
            mock_socket = MagicMock()
            socket_factory.return_value = mock_socket
            mock_socket.recv.return_value = b'CONNECTED\n\n\x00'
            client = StompClient('localhost', 54321)
            client.connect()
        mock_socket.sendall.assert_called_once_with(b'CONNECT\naccept-version:1.2\nhost:localhost\n\n\x00')

    def test_stomp_client_cleans_up_subscriptions_on_close(self):
        with patch('socket.socket') as socket_factory:
            with patch('uuid.uuid4') as mock_uuid:
                mock_uuid.return_value = '42'
                mock_socket = MagicMock()
                socket_factory.return_value = mock_socket
                mock_socket.recv.return_value = b'CONNECTED\n\n\x00'
                client = StompClient('localhost', 54321)
                client.connect()
                client.subscribe('bob')
                client.close()
        mock_socket.sendall.assert_called_with(b'UNSUBSCRIBE\nid:42\n\n\x00')


class JsonRpcTest(TestCase):
    def test_jsonrpc_client_subscribes_to_response_queue(self):
        with patch('virtwho.virt.vdsm.jsonrpc.StompClient') as mock_client_factory:
            mock_stomp_client = MagicMock()
            mock_client_factory.return_value = mock_stomp_client
            jsonrpc_client = JsonRpcClient('localhost', '54321')
            jsonrpc_client.connect()
            mock_stomp_client.subscribe.assert_called_once_with(jsonrpc_client.id)

    def test_jsonrpc_client_payload_encoding_with_params(self):
        with patch('virtwho.virt.vdsm.jsonrpc.StompClient') as mock_client_factory:
            with patch('uuid.uuid4') as mock_uuid:
                mock_uuid.return_value = 42
                mock_stomp_client = MagicMock()
                mock_client_factory.return_value = mock_stomp_client
                mock_stomp_client.receive.return_value = StompFrame('MESSAGE', body=b'{"result":"bar"}')
                jsonrpc_client = JsonRpcClient('localhost', '54321')
                jsonrpc_client.connect()
                result = jsonrpc_client.call('test', foo='bar')
                self.assertEquals(result, u'bar')
                expected_command = u'SEND'
                expected_headers = {
                    u'content-length': 74,
                    u'destination': u'jms.topic.vdsm_requests',
                    u'reply-to': u'42'
                }
                expected_data = {
                    "params": {"foo": "bar"}, "jsonrpc": "2.0", "method": "test", "id": "42"
                }

                # The data in the stomp_client.send call (2nd, and 3rd arguments) are dicts dumped
                # as json to a bytes object. Because dictionaries are not guaranteed to be iterated
                # over in the same order, these dicts do not appear equal on python 3.
                # Comparing these using assertEqual will call the registered method associated with
                # dicts (which does not care about order).
                send_args = mock_stomp_client.send.call_args
                self.assertEqual(send_args[0][0], expected_command)
                self.assertEqual(send_args[0][1], expected_headers)
                actual_data = json.loads(send_args[0][2])
                self.assertEqual(actual_data, expected_data)

    def test_jsonrpc_client_payload_encoding_without_params(self):
        with patch('virtwho.virt.vdsm.jsonrpc.StompClient') as mock_client_factory:
            with patch('uuid.uuid4') as mock_uuid:
                mock_uuid.return_value = 42
                mock_stomp_client = MagicMock()
                mock_client_factory.return_value = mock_stomp_client
                mock_stomp_client.receive.return_value = StompFrame('MESSAGE', body=b'{"result":"bar"}')
                jsonrpc_client = JsonRpcClient('localhost', '54321')
                jsonrpc_client.connect()
                result = jsonrpc_client.call('test')
                self.assertEqual(result, u'bar')
                mock_stomp_client.send.assert_called_with(u'SEND', {
                    u'content-length': 48,
                    u'destination': u'jms.topic.vdsm_requests',
                    u'reply-to': u'42'
                }, b'{"jsonrpc": "2.0", "method": "test", "id": "42"}')

    def test_jsonrpc_client_errs_on_error_frame(self):
        with patch('virtwho.virt.vdsm.jsonrpc.StompClient') as mock_client_factory:
            with patch('uuid.uuid4') as mock_uuid:
                mock_uuid.return_value = 42
                mock_stomp_client = MagicMock()
                mock_client_factory.return_value = mock_stomp_client
                mock_stomp_client.receive.return_value = StompFrame('ERROR', body=b'uh-oh!')
                jsonrpc_client = JsonRpcClient('localhost', '54321')
                jsonrpc_client.connect()
                self.assertRaises(RuntimeError, jsonrpc_client.call, 'test')

    def test_jsonrpc_client_errs_on_error_json(self):
        with patch('virtwho.virt.vdsm.jsonrpc.StompClient') as mock_client_factory:
            with patch('uuid.uuid4') as mock_uuid:
                mock_uuid.return_value = 42
                mock_stomp_client = MagicMock()
                mock_client_factory.return_value = mock_stomp_client
                mock_stomp_client.receive.return_value = StompFrame('MESSAGE', body=b'{"error":{"message":"foo"}}')
                jsonrpc_client = JsonRpcClient('localhost', '54321')
                jsonrpc_client.connect()
                self.assertRaises(RuntimeError, jsonrpc_client.call, 'test')
