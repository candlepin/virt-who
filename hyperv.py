
import sys
import httplib
import urlparse
import base64
from uuid import uuid1

# Import XML parser
try:
    from elementtree import ElementTree
except ImportError:
    from xml.etree import ElementTree

import ntlm

NAMESPACES = {
    's':     'http://www.w3.org/2003/05/soap-envelope',
    'wsa':   'http://schemas.xmlsoap.org/ws/2004/08/addressing',
    'wsman': 'http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd',
    'wsen':  'http://schemas.xmlsoap.org/ws/2004/09/enumeration'
}

ENVELOPE = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope """ + " ".join(('xmlns:%s="%s"' % (k, v) for k, v in NAMESPACES.items())) + """>
    %s
    %s
</s:Envelope>"""

def getHeader(action):
    return """<s:Header>
        <wsa:Action s:mustUnderstand="true">""" + NAMESPACES['wsen'] + "/" + action + """</wsa:Action>
        <wsa:To s:mustUnderstand="true">%(url)s</wsa:To>
        <wsman:ResourceURI s:mustUnderstand="true">http://schemas.microsoft.com/wbem/wsman/1/wmi/%(namespace)s/*</wsman:ResourceURI>
        <wsa:MessageID s:mustUnderstand="true">uuid:""" + str(uuid1()) + """</wsa:MessageID>
        <wsa:ReplyTo>
            <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
        </wsa:ReplyTo>
    </s:Header>"""

ENUMERATE_BODY = """<s:Body>
        <wsen:Enumerate>
            <wsman:Filter Dialect="http://schemas.microsoft.com/wbem/wsman/1/WQL">%(query)s</wsman:Filter>
        </wsen:Enumerate>
    </s:Body>"""

PULL_BODY = """<s:Body>
        <wsen:Pull>
            <wsen:EnumerationContext>%(EnumerationContext)s</wsen:EnumerationContext>
        </wsen:Pull>
    </s:Body>"""

ENUMERATE_XML = ENVELOPE % (getHeader("Enumerate"), ENUMERATE_BODY)
PULL_XML = ENVELOPE % (getHeader("Pull"), PULL_BODY)

class HyperVSoap(object):
    def __init__(self, url, connection, headers):
        self.url = url
        self.connection = connection
        self.headers = headers

    def post(self, body):
        self.headers["Content-Length"] = "%d" % len(body)
        self.connection.request("POST", self.url, body=body, headers=self.headers)
        response = self.connection.getresponse()
        if response.status == 401:
            raise HyperVAuthFailed("Authentication failed")
        if response.status != 200:
            raise HyperVException("Communication with Hyper-V failed, HTTP error: %d" % response.status)
        if response is None:
            raise HyperVException("No reply from Hyper-V")
        return response

    @classmethod
    def _Instance(cls, xml):
        def stripNamespace(tag):
            return tag[tag.find("}") + 1:]
        children = xml.getchildren()
        if len(children) < 1:
            return None
        child = children[0]
        properties = {}
        for ch in child.getchildren():
            properties[stripNamespace(ch.tag)] = ch.text
        return properties

    def Enumerate(self, query, namespace="root/virtualization"):
        data = ENUMERATE_XML % { 'url': self.url, 'query': query, 'namespace': namespace }
        response = self.post(data)
        d = response.read()
        xml = ElementTree.fromstring(d)
        if xml.tag != "{%(s)s}Envelope" % NAMESPACES:
            raise HyperVException("Wrong reply format")
        responses = xml.findall("{%(s)s}Body/{%(wsen)s}EnumerateResponse" % NAMESPACES)
        if len(responses) < 1:
            raise HyperVException("Wrong reply format")
        contexts = responses[0].getchildren()
        if len(contexts) < 1:
            raise HyperVException("Wrong reply format")

        if contexts[0].tag != "{%(wsen)s}EnumerationContext" % NAMESPACES:
            raise HyperVException("Wrong reply format")
        return contexts[0].text

    def _PullOne(self, uuid, namespace):
        data = PULL_XML % { 'url': self.url, 'EnumerationContext': uuid, 'namespace': namespace }
        response = self.post(data)
        d = response.read()
        xml = ElementTree.fromstring(d)
        if xml.tag != "{%(s)s}Envelope" % NAMESPACES:
            raise HyperVException("Wrong reply format")
        responses = xml.findall("{%(s)s}Body/{%(wsen)s}PullResponse" % NAMESPACES)
        if len(responses) < 0:
            raise HyperVException("Wrong reply format")

        uuid = None
        instance = None

        for node in responses[0].getchildren():
            if node.tag == "{%(wsen)s}EnumerationContext" % NAMESPACES:
                uuid = node.text
            elif node.tag == "{%(wsen)s}Items" % NAMESPACES:
                instance = HyperVSoap._Instance(node)

        return uuid, instance

    def Pull(self, uuid, namespace="root/virtualization"):
        instances = []
        while uuid is not None:
            uuid, instance = self._PullOne(uuid, namespace)
            if instance is not None:
                instances.append(instance)
        return instances


class HyperVException(Exception):
    pass

class HyperVAuthFailed(HyperVException):
    pass


class HyperV:
    def __init__(self, logger, url, username, password):
        self.logger = logger
        self.username = username
        self.password = password

        # Parse URL and create proper one
        if "//" not in url:
            url = "//" + url
        parsed = urlparse.urlsplit(url, "http")
        if ":" not in parsed[1]:
            if parsed[0] == "https":
                self.host = parsed[1] + ":5986"
            else:
                self.host = parsed[1] + ":5985"
        else:
            self.host = parsed[1]
        if parsed[2] == "":
            path = "wsman"
        else:
            path = parsed[2]
        self.url = urlparse.urlunsplit((parsed[0], self.host, path, "", ""))

        logger.debug("Hyper-V url: %s" % self.url)

        # Check if we have domain defined and set flags accordingly
        user_parts = username.split('\\', 1)
        if len(user_parts) == 1:
            self.username = user_parts[0]
            self.domainname = ''
            self.type1_flags = ntlm.NTLM_TYPE1_FLAGS & ~ntlm.NTLM_NegotiateOemDomainSupplied
        else:
            self.domainname = user_parts[0].upper()
            self.username = user_parts[1]
            self.type1_flags = ntlm.NTLM_TYPE1_FLAGS

    def connect(self):
        if self.url.startswith("https"):
            connection = httplib.HTTPSConnection(self.host)
        else:
            connection = httplib.HTTPConnection(self.host)

        headers = {}
        headers["Connection"] = "Keep-Alive"
        headers["Content-Length"] = "0"

        connection.request("POST", self.url, headers=headers)
        response = connection.getresponse()
        response.read()
        if response.status == 200:
            return connection, headers
        elif response.status == 404:
            raise HyperVException("Invalid HyperV url: %s" % self.url)
        elif response.status != 401:
            raise HyperVException("Unable to connect to HyperV at: %s" % self.url)
        # 401 - need authentication

        authenticate_header = response.getheader("WWW-Authenticate", "")
        if 'Negotiate' in authenticate_header:
            try:
                self.ntlmAuth(connection, headers)
            except HyperVAuthFailed:
                if 'Basic' in authenticate_header:
                    self.basicAuth(connection, headers)
                else:
                    raise
        elif 'Basic' in authenticate_header:
            self.basicAuth(connection, headers)
        else:
            raise HyperVAuthFailed("Server doesn't known any supported authentication method")
        return connection, headers

    def ntlmAuth(self, connection, headers):
        self.logger.debug("Using NTLM authentication")
        # Use ntlm
        headers["Authorization"] = "Negotiate %s" % ntlm.create_NTLM_NEGOTIATE_MESSAGE(self.username, self.type1_flags)

        connection.request("POST", self.url, headers=headers)
        response = connection.getresponse()
        response.read()
        if response.status != 401:
            raise HyperVAuthFailed("NTLM negotiation failed")

        auth_header = response.getheader("WWW-Authenticate", "")
        if auth_header == "":
            raise HyperVAuthFailed("NTLM negotiation failed")

        nego, challenge = auth_header.split(" ")
        if nego != "Negotiate":
            print >>sys.stderr, "Wrong header: ", auth_header
            sys.exit(1)

        nonce, flags = ntlm.parse_NTLM_CHALLENGE_MESSAGE(challenge)
        headers["Authorization"] = "Negotiate %s" % ntlm.create_NTLM_AUTHENTICATE_MESSAGE(nonce, self.username, self.domainname, self.password, flags)

        connection.request("POST", self.url, headers=headers)
        response = connection.getresponse()
        response.read()
        if response.status == 200:
            headers.pop("Authorization")
            self.logger.debug("NTLM authentication successful")
        else:
            raise HyperVAuthFailed("NTLM negotiation failed")

    def basicAuth(self, connection, headers):
        self.logger.debug("Using Basic authentication")

        passphrase = "%s:%s" % (self.username, self.password)
        encoded = base64.encodestring(passphrase)
        headers["Authorization"] = "Basic %s" % encoded.replace('\n', '')

    @classmethod
    def decodeWinUUID(cls, uuid):
        """ Windows UUID needs to be decoded using following key
        From: {78563412-AB90-EFCD-1234-567890ABCDEF}
        To:    12345678-90AB-CDEF-1234-567890ABCDEF
        """
        if uuid[0] == "{":
            s = uuid[1:-1]
        else:
            s = uuid
        return s[6:8] + s[4:6] + s[2:4] + s[0:2] + "-" + s[11:13] + s[9:11] + "-" + s[16:18] + s[14:16] + s[18:]

    def getHostGuestMapping(self):
        guests = []
        connection, headers = self.connect()
        hypervsoap = HyperVSoap(self.url, connection, headers)
        # SettingType == 3 means current setting, 5 is snapshot - we don't want snapshots
        uuid = hypervsoap.Enumerate("select BIOSGUID from Msvm_VirtualSystemSettingData where SettingType = 3")
        for instance in hypervsoap.Pull(uuid):
            guests.append(HyperV.decodeWinUUID(instance["BIOSGUID"]))
        uuid = hypervsoap.Enumerate("select UUID from Win32_ComputerSystemProduct", "root/cimv2")
        host = None
        for instance in hypervsoap.Pull(uuid, "root/cimv2"):
            host = HyperV.decodeWinUUID(instance["UUID"])
        return { host: guests }

    def ping(self):
        return True

if __name__ == '__main__':
    # TODO: read from config
    if len(sys.argv) < 4:
        print "Usage: %s url username password"
        sys.exit(0)

    import logging
    logger = logging.Logger("")
    logger.addHandler(logging.StreamHandler())
    hyperv = HyperV(logger, sys.argv[1], sys.argv[2], sys.argv[3])
    print hyperv.getHostGuestMapping()
