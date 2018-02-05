from __future__ import print_function
from mock import patch, MagicMock, PropertyMock

from base import TestBase

from virtwho.util import RequestsXmlrpcTransport


class FakeParser(object):
    def feed(self, arg):
        self.arg = arg

    def close(self):
        pass


class TestRequestsXmlrpcTransport(TestBase):
    @patch('requests.Response')
    def test_use_response_content(self, resp):
        parser_return_value = [FakeParser(), FakeParser()]

        transport = RequestsXmlrpcTransport('http://localhost')
        transport.getparser = MagicMock(return_value=parser_return_value)

        p = PropertyMock()
        type(resp).content = p
        transport.parse_response(resp)

        assert p.called, 'Response.content should be used instead'
