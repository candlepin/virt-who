# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
# Module for JSON-RPC over STOMP, part of virt-who
#
# Copyright (C) 2018 Kevin Howell <khowell@redhat.com>
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
Minimal implementation of the JSON-RPC specification (http://www.jsonrpc.org/specification) over STOMP to enable a
client for VDSM.

There are better developed JSON-RPC libraries for Python available (such as jsonrpclib), but for RHEL/CentOS, at the
time of writing, only available in EPEL.
"""

import json
import ssl
from six import text_type
import uuid

from virtwho.virt.vdsm.stomp import StompClient


class JsonRpcClient(object):
    """JSON-RPC 2.0 over STOMP client"""

    def __init__(self, host, port, ssl_context=None, timeout=None):
        """Create a JSON-RPC over STOMP client.

        :param host: STOMP server hostname.
        :param port: STOMP server port.
        :param ssl_context: SSL context if using TLS or None.
        :param timeout: timeout for blocking operations.
        """
        self.id = text_type(uuid.uuid4())
        self.stomp = StompClient(host, port, ssl_context=ssl_context, timeout=timeout)

    def connect(self):
        """Connect to the STOMP server."""
        self.stomp.connect()
        self.stomp.subscribe(self.id)

    def close(self):
        """Close the underlying connection."""
        self.stomp.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args, **kwargs):
        self.close()

    def call(self, method, **params):
        """Call a method via JSON-RPC.

        :param method: name of method.
        :param params: parameters for the method.
        :return: the result as a dict if successful.
        :raises: RuntimeError if the result is an error or cannot be decoded.
        """
        data_object = {
            'jsonrpc': '2.0',
            'method': method,
            'id': text_type(uuid.uuid4())
        }
        if params:
            data_object['params'] = {}
            for key, value in params.items():
                data_object['params'][key] = value
        data = json.dumps(data_object).encode('utf-8')
        self.stomp.send('SEND', {
            'destination': 'jms.topic.vdsm_requests',
            'content-length': len(data),
            'reply-to': self.id,
        }, data)
        response = self.stomp.receive()
        if response.command == 'ERROR':
            raise RuntimeError(response.body.decode('utf-8'))
        response_json = json.loads(response.body.decode('utf-8'))
        if 'error' in response_json:
            # TODO log verbose error object?
            raise RuntimeError(response_json['error']['message'])
        return response_json['result']


def main():
    """Utility for one-off calls to VDSM via JSON-RPC over STOMP.

    Example invocation:

    python -m virtwho.virt.vdsm.jsonrpc
        --cert /etc/pki/vdsm/certs/vdsmcert.pem
        --key /etc/pki/vdsm/keys/vdsmkey.pem
        $HOSTNAME 54321
        Host.getVMList onlyUUID=False
    """
    import argparse

    parser = argparse.ArgumentParser(description='vdsm over jsonrpc utility')

    parser.add_argument('--key', help='path to key pem file')
    parser.add_argument('--cert', help='path to cert pem file')
    parser.add_argument('host', help='hostname')
    parser.add_argument('port', help='port')
    parser.add_argument('method', help='method to call via JSON-RPC')
    parser.add_argument('args', help='arguments for the call with format $key=$value', nargs='*')
    args = parser.parse_args()

    ssl_enabled = 'cert' in args and 'key' in args
    if ('key' in args or 'cert' in args) and not ssl_enabled:
        raise ValueError('Must provide both --cert and --key for SSL')

    ssl_context = None
    if ssl_enabled:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        ssl_context.verify_mode = ssl.CERT_NONE
        ssl_context.load_cert_chain(args.cert, args.key)

    # parse method args
    method_args = {}
    for arg in args.args:
        key, value = arg.split('=')
        key = key.strip()
        value = value.strip()
        if value.lower() == 'true':
            value = True
        if value.lower() == 'false':
            value = False
        method_args[key] = value

    with JsonRpcClient(args.host, args.port, ssl_context=ssl_context) as jsonrpc_client:
        print(json.dumps(jsonrpc_client.call(args.method, **method_args), indent=True))


if __name__ == '__main__':
    main()
