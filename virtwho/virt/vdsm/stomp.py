# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
# Module for STOMP messaging, part of virt-who
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
Implements enough of the STOMP specification (https://stomp.github.io/stomp-specification-1.2.html) to enable
implementation of a client for VDSM's JSON-RPC API over STOMP. Could be easily improved to be a general STOMP client;
TODOs and FIXMEs document known gaps.

There are better developed STOMP libraries for Python available (such as stomper), but for RHEL/CentOS, at the time of
writing, only available in EPEL.
"""

import logging
import socket
from six import text_type
import uuid

log = logging.getLogger(__name__)


class StompFrame(object):
    """STOMP frame as described in the STOMP specification."""

    def __init__(self, command, headers=None, body=None):
        """Create a new StompFrame.

        :param command: STOMP command as a string (ex. 'CONNECT').
        :param headers: dict containing STOMP headers.
        :param body: body as bytes.
        """
        self.command = command
        self.headers = headers or {}
        self.body = body or b''

    @classmethod
    def from_bytes(cls, data):
        """Decode bytes into a StompFrame.

        :param data: a single STOMP frame as bytes.
        :return: a StompFrame.
        :raises:
        """
        parts = [part for part in data.splitlines()]
        if not parts:
            raise IOError('Cannot parse data as STOMP frame')

        # find indexOf empty line, this is the indicator what follows is body
        try:
            end_of_headers_index = parts.index(b'')
        except ValueError:
            raise IOError('Cannot parse data as STOMP frame')

        command_part = parts[0]
        header_parts = parts[1:end_of_headers_index]
        body_parts = parts[end_of_headers_index:]  # TODO assert that remaining data ends in EOF (NULL)

        return StompFrame(
            command=command_part.decode('utf-8'),
            headers=cls._decode_headers(header_parts),
            body=cls._unescape_bytes(b''.join(body_parts)[:-1]),  # TODO handle content-length
        )

    def to_bytes(self):
        """Encode the STOMP frame as bytes.

        :return: bytes.
        """
        frame = b'\n'.join([
            self.command.encode('utf-8'),
            self._encode_headers(),
            self.body
        ])
        frame = frame + b'\x00'
        return frame

    def _encode_headers(self):
        if not self.headers:
            return b''
        return b'\n'.join(
            [b':'.join(
                [
                    self._escape_bytes(key.encode('utf-8')),
                    self._escape_bytes(text_type(value).encode('utf-8')),
                ]
            ) for key, value in sorted(self.headers.items())]  # sort the headers for predictable messages
        ) + b'\n'

    @classmethod
    def _decode_headers(cls, data):
        headers = {}
        for line in data:
            key, value = line.split(b':')  # TODO err intelligently if more than one ':' detected
            key = cls._unescape_bytes(key).decode('utf-8')
            value = cls._unescape_bytes(value).decode('utf-8')
            if key not in headers:  # first value wins
                headers[key] = value
        return headers

    @staticmethod
    def _escape_bytes(data):
        if data is None:
            return b''
        data = data.replace(b'\\', b'\\\\')  # \ -> \\
        data = data.replace(b'\r', b'\\r')   # CR -> \r
        data = data.replace(b'\n', b'\\n')   # LF -> \n
        data = data.replace(b':', b'\\c')    # : -> \c
        return data

    @staticmethod
    def _unescape_bytes(data):
        data = data.replace(b'\\c', b':')    # \c -> :
        data = data.replace(b'\\n', b'\n')   # \n -> LF
        data = data.replace(b'\\r', b'\r')   # \r -> CR
        # TODO could check here that there are illegal escape sequences (ex. \t), see STOMP spec for details
        data = data.replace(b'\\\\', b'\\')  # \\ -> \
        return data


class StompClient(object):
    """Minimal STOMP client with SSL support."""

    def __init__(self, host, port, ssl_context=None, timeout=None):
        """Create a new STOMP client.

        :param host: STOMP server hostname.
        :param port: STOMP server port.
        :param ssl_context: SSL context if using TLS.
        :param timeout: timeout for blocking operations.
        """
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.timeout = timeout
        self.socket = None
        self.buffer = b''  # FIXME for performance, could construct a buffer and then recv_into instead...
        self.subscription_ids = []

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args, **kwargs):
        self.close()

    def connect(self):
        """Connect to the STOMP server.

        Sends a STOMP CONNECT and consumes the subsequent CONNECTED message.

        :raises: IOError if no connection attempts succeed.
        """
        for family, _, _, _, addr in socket.getaddrinfo(self.host, self.port):
            try:
                self.socket = socket.socket(family)
                self.socket.settimeout(self.timeout)
                if self.ssl_context:
                    if hasattr(self.ssl_context, 'wrap_socket'):
                        self.socket = self.ssl_context.wrap_socket(self.socket)
                        self.socket.connect(addr)
                    else:
                        import M2Crypto.SSL.Connection
                        self.socket = M2Crypto.SSL.Connection(self.ssl_context)
                        self.socket.connect((self.host, int(self.port)))
                message = StompFrame('CONNECT', headers={
                    'accept-version': '1.2',
                    'host': self.host,
                })
                self.socket.sendall(message.to_bytes())
                self._validate_connected(self._recv_frame())
                return  # success connecting
            except (socket.error, IOError) as e:
                log.warning('Unable to connect %s:%s: %s' % (self.host, self.port, text_type(e)))
        raise IOError('Unable to connect to %s:%s' % (self.host, self.port))

    @staticmethod
    def _validate_connected(data):
        frame = StompFrame.from_bytes(data)
        if frame.command != 'CONNECTED':
            raise IOError('Did not parse expected CONNECTED frame')

    def close(self):
        """Close STOMP server connection, unsubscribing from any tracked subscriptions."""
        for subscription_id in self.subscription_ids:
            self.unsubscribe(subscription_id)
        self.socket.close()
        self.socket = None

    def send(self, command, headers=None, data=None):
        """Construct and send a STOMP frame.

        :param command: STOMP command as a string.
        :param headers: dict containing STOMP headers.
        :param data: STOMP body as bytes.
        """
        self.socket.sendall(StompFrame(command, headers, data).to_bytes())

    def receive(self):
        """Receive a STOMP frame.

        :return: a StompFrame.
        """
        return StompFrame.from_bytes(self._recv_frame())

    def _recv_frame(self):
        while b'\x00' not in self.buffer:
            self.buffer += self.socket.recv(4096)
        frame, self.buffer = self.buffer.split(b'\x00', 1)
        # add null byte back to frame
        frame += b'\x00'
        return frame

    def subscribe(self, destination):
        """Subscribe to a queue or topic.

        :param destination: Name of the queue or topic to subscribe to.
        :return: randomly generated subscription ID.
        """
        subscription_id = uuid.uuid4()
        self.send('SUBSCRIBE', {
            'id': subscription_id,
            'destination': destination,
        })
        self.subscription_ids.append(subscription_id)
        return subscription_id

    def unsubscribe(self, subscription_id):
        """Unsubscribe from a given subscription ID.

        :param subscription_id: id returned by subscribe call.
        """
        self.send('UNSUBSCRIBE', {
            'id': subscription_id,
        })
