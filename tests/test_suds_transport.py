from __future__ import print_function

import unittest

from virtwho.virt.esx.suds.transport import Request, Reply


class TestRequestUnicode(unittest.TestCase):
    """Regression tests for Request/Reply.__unicode__ with str vs bytes messages.

    Python 3.14+ pytest eagerly formats log arguments, which triggers
    __str__ -> __unicode__ on Request objects during HttpTransport.send().
    Previously, __unicode__ unconditionally called message.decode() which
    fails when message is a str rather than bytes.
    """

    def test_request_str_message(self):
        r = Request("http://example.com", message="hello")
        result = str(r)
        self.assertIn("hello", result)
        self.assertIn("http://example.com", result)

    def test_request_bytes_message(self):
        r = Request("http://example.com", message=b"hello")
        result = str(r)
        self.assertIn("hello", result)

    def test_request_none_message(self):
        r = Request("http://example.com")
        result = str(r)
        self.assertNotIn("MESSAGE", result)

    def test_reply_str_message(self):
        r = Reply(200, {}, "response body")
        result = str(r)
        self.assertIn("response body", result)
        self.assertIn("200", result)

    def test_reply_bytes_message(self):
        r = Reply(200, {}, b"response body")
        result = str(r)
        self.assertIn("response body", result)
