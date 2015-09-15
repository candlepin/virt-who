"""
Module for communcating with Hyper-V, part of virt-who

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

import sys
import os
import httplib
import urlparse
import base64

import virt

try:
    from uuid import uuid1
except ImportError:
    import subprocess

    def uuid1():
        # fallback to calling commandline uuidgen
        return subprocess.Popen(["uuidgen"], stdout=subprocess.PIPE).communicate()[0].strip()

# Import XML parser
try:
    from elementtree import ElementTree
except ImportError:
    from xml.etree import ElementTree

import ntlm


class HyperVSoapGenerator(object):
    def __init__(self, url):
        self.url = url
        self.virtualization_namespace = 'root/virtualization'

    @property
    def namespaces(self):
        return {
            's': 'http://www.w3.org/2003/05/soap-envelope',
            'wsa': 'http://schemas.xmlsoap.org/ws/2004/08/addressing',
            'wsman': 'http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd',
            'wsen': 'http://schemas.xmlsoap.org/ws/2004/09/enumeration',
        }

    vsms_namespace = 'http://schemas.microsoft.com/wbem/wsman/1/wmi/%(ns)s/Msvm_VirtualSystemManagementService'
    si_namespace = 'http://schemas.microsoft.com/wbem/wsman/1/wmi/%(ns)s/Msvm_SummaryInformation'

    def envelope(self, header, body):
        return """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope """ + " ".join(('xmlns:%s="%s"' % (k, v) for k, v in self.namespaces.items())) + """>
    %(header)s
    %(body)s
</s:Envelope>""" % {'header': header, 'body': body}

    def getHeader(self, action, action_namespace=None,
                  additional_headers=None, resourceURI='*',
                  resource_namespace='root/virtualization'):
        if action_namespace is None:
            action_namespace = self.namespaces['wsen']

        if additional_headers is None:
            additional_headers = ""

        return """<s:Header>
            <wsa:Action s:mustUnderstand="true">%(action_namespace)s/%(action)s</wsa:Action>
            <wsa:To s:mustUnderstand="true">%(url)s</wsa:To>
            <wsman:ResourceURI s:mustUnderstand="true">
                http://schemas.microsoft.com/wbem/wsman/1/wmi/%(resource_namespace)s/%(resourceURI)s
            </wsman:ResourceURI>
            <wsa:MessageID s:mustUnderstand="true">uuid:%(uuid)s</wsa:MessageID>
            <wsa:ReplyTo>
                <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
            </wsa:ReplyTo>%(additional_headers)s
        </s:Header>""" % {
            'uuid': str(uuid1()),
            'url': self.url,
            'action': action,
            'action_namespace': action_namespace,
            'additional_headers': additional_headers,
            'resourceURI': resourceURI,
            'resource_namespace': resource_namespace
        }

    def enumerateXML(self, query, namespace):
        body = """<s:Body>
        <wsen:Enumerate>
            <wsman:Filter Dialect="http://schemas.microsoft.com/wbem/wsman/1/WQL">%(query)s</wsman:Filter>
        </wsen:Enumerate>
    </s:Body>""" % {'query': query}

        return self.envelope(
            self.getHeader('Enumerate', resource_namespace=namespace),
            body)

    def pullXML(self, enumerationContext, namespace):
        body = """<s:Body>
        <wsen:Pull>
            <wsen:EnumerationContext>%(EnumerationContext)s</wsen:EnumerationContext>
        </wsen:Pull>
    </s:Body>""" % {'EnumerationContext': enumerationContext}
        return self.envelope(
            self.getHeader("Pull", resource_namespace=namespace),
            body)

    def getSummaryInformationXML(self, namespace):
        body = """<s:Body>
        <wsman:GetSummaryInformation_INPUT xmlns:p="%(namespace)s">
            <p:RequestedInformation>0</p:RequestedInformation>
            <p:RequestedInformation>1</p:RequestedInformation>
            <p:RequestedInformation>100</p:RequestedInformation>
        </wsman:GetSummaryInformation_INPUT>
    </s:Body>""" % {'namespace': (self.vsms_namespace % {'ns': namespace})}

        return self.envelope(
            self.getHeader("GetSummaryInformation",
                           action_namespace=self.vsms_namespace % {'ns': namespace},
                           resourceURI="Msvm_VirtualSystemManagementService",
                           resource_namespace=namespace,
                           additional_headers="""
        <wsman:SelectorSet>
            <wsman:Selector Name="CreationClassName">Msvm_VirtualSystemManagementService</wsman:Selector>
            <wsman:Selector Name="SystemCreationClassName">Msvm_ComputerSystem</wsman:Selector>
        </wsman:SelectorSet>"""),
            body)


ENABLED_STATE_TO_GUEST_STATE = {
    '2': virt.Guest.STATE_RUNNING,
    '3': virt.Guest.STATE_SHUTOFF,
    '4': virt.Guest.STATE_SHUTINGDOWN,
    '9': virt.Guest.STATE_PAUSED,
    '32768': virt.Guest.STATE_PAUSED,
    '32769': virt.Guest.STATE_PMSUSPENDED
}


class HyperVSoap(object):
    def __init__(self, url, connection, headers, logger):
        self.url = url
        self.connection = connection
        self.headers = headers
        self.generator = HyperVSoapGenerator(self.url)
        self.logger = logger

    def post(self, body):
        self.headers["Content-Length"] = "%d" % len(body)
        self.headers["Content-Type"] = "application/soap+xml;charset=UTF-8"
        self.connection.request("POST", self.url, body=body, headers=self.headers)
        response = self.connection.getresponse()
        if response.status == 401:
            raise HyperVAuthFailed("Authentication failed")
        if response.status != 200:
            data = response.read()
            xml = ElementTree.fromstring(data)
            errorcode = xml.find('.//{http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/MSFT_WmiError}error_Code')
            # Suppress reporting of invalid namespace, because we're testing
            # both old and new namespaces that HyperV uses
            if errorcode is None or errorcode.text != '2150858778':
                self.logger.debug("Invalid response (%d) from Hyper-V: %s", response.status, data)
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
        data = self.generator.enumerateXML(query=query, namespace=namespace)
        response = self.post(data)
        d = response.read()
        xml = ElementTree.fromstring(d)
        if xml.tag != "{%(s)s}Envelope" % self.generator.namespaces:
            raise HyperVException("Wrong reply format")
        responses = xml.findall("{%(s)s}Body/{%(wsen)s}EnumerateResponse" % self.generator.namespaces)
        if len(responses) < 1:
            raise HyperVException("Wrong reply format")
        contexts = responses[0].getchildren()
        if len(contexts) < 1:
            raise HyperVException("Wrong reply format")

        if contexts[0].tag != "{%(wsen)s}EnumerationContext" % self.generator.namespaces:
            raise HyperVException("Wrong reply format")
        return contexts[0].text

    def _PullOne(self, uuid, namespace):
        data = self.generator.pullXML(enumerationContext=uuid, namespace=namespace)
        response = self.post(data)
        d = response.read()
        xml = ElementTree.fromstring(d)
        if xml.tag != "{%(s)s}Envelope" % self.generator.namespaces:
            raise HyperVException("Wrong reply format")
        responses = xml.findall("{%(s)s}Body/{%(wsen)s}PullResponse" % self.generator.namespaces)
        if len(responses) < 0:
            raise HyperVException("Wrong reply format")

        uuid = None
        instance = None

        for node in responses[0].getchildren():
            if node.tag == "{%(wsen)s}EnumerationContext" % self.generator.namespaces:
                uuid = node.text
            elif node.tag == "{%(wsen)s}Items" % self.generator.namespaces:
                instance = HyperVSoap._Instance(node)

        return uuid, instance

    def Pull(self, uuid, namespace="root/virtualization"):
        instances = []
        while uuid is not None:
            uuid, instance = self._PullOne(uuid, namespace)
            if instance is not None:
                instances.append(instance)
        return instances

    def Invoke_GetSummaryInformation(self, namespace):
        '''
        Get states of all virtual machines present on the system and
        return dict where `ElementName` is key and `virt.GUEST.STATE_*` is value.
        '''
        data = self.generator.getSummaryInformationXML(namespace)
        response = self.post(data)
        d = response.read()
        xml = ElementTree.fromstring(d)
        if xml.tag != "{%(s)s}Envelope" % self.generator.namespaces:
            raise HyperVException("Wrong reply format")
        responses = xml.findall("{%(s)s}Body/{%(vsms)s}GetSummaryInformation_OUTPUT" % {
            's': self.generator.namespaces['s'],
            'vsms': self.generator.vsms_namespace % {'ns': namespace}
        })
        if len(responses) < 0:
            raise HyperVException("Wrong reply format")
        info = {}
        si_namespace = self.generator.si_namespace % {'ns': namespace}
        for node in responses[0].getchildren():
            if 'SummaryInformation' in node.tag:
                elementName = node.find("{%(si)s}ElementName" % {'si': si_namespace}).text
                enabledState = node.find("{%(si)s}EnabledState" % {'si': si_namespace}).text
                info[elementName] = ENABLED_STATE_TO_GUEST_STATE.get(enabledState, virt.Guest.STATE_UNKNOWN)
        return info


class HyperVException(virt.VirtError):
    pass


class HyperVAuthFailed(HyperVException):
    pass


class HyperV(virt.Virt):
    CONFIG_TYPE = "hyperv"

    def __init__(self, logger, config):
        super(HyperV, self).__init__(logger, config)
        url = config.server
        self.username = config.username
        self.password = config.password

        # First try to use old API (root/virtualization namespace) if doesn't
        # work, go with root/virtualization/v2
        self.useNewApi = False

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
        user_parts = self.username.split('\\', 1)
        if len(user_parts) == 1:
            self.username = user_parts[0]
            self.domainname = ''
            self.type1_flags = ntlm.NTLM_TYPE1_FLAGS & ~ntlm.NTLM_NegotiateOemDomainSupplied
        else:
            self.domainname = user_parts[0].upper()
            self.username = user_parts[1]
            self.type1_flags = ntlm.NTLM_TYPE1_FLAGS

    def connect(self):
        host, port = self.host.split(':')
        proxy = False
        protocol = self.url.partition("://")[0]
        for env in ['%s_proxy' % protocol.lower(), '%s_PROXY' % protocol.upper()]:
            if env in os.environ:
                proxy_url = os.environ[env]
                if "://" not in proxy_url:
                    # Add http or https to proxy_url otherwise urlsplit
                    # won't parse it correctly
                    proxy_url = "%s://%s" % (protocol, proxy_url)
                r = urlparse.urlsplit(proxy_url)
                host = r.hostname
                port = r.port or (80 if protocol == 'http' else 443)
                proxy = True
                break

        if protocol == "https":
            connection = httplib.HTTPSConnection(host, int(port))
        else:
            connection = httplib.HTTPConnection(host, int(port))

        if proxy:
            host, port = self.host.split(':')
            try:
                connection.set_tunnel(host, int(port))
            except AttributeError:
                # set_tunnel method is private in python 2.6
                connection._set_tunnel(host, int(port))

        headers = {}
        headers["Connection"] = "Keep-Alive"
        headers["Content-Length"] = "0"

        connection.request("POST", '/wsman', headers=headers)
        response = connection.getresponse()
        response.read()

        if proxy:
            # Tunnel must be cleared after first request otherwise
            # the CONNECT is send to the hyperv server in subsequent requests
            try:
                connection.set_tunnel(None, None)
            except AttributeError:
                # set_tunnel method is private in python 2.6
                connection._set_tunnel(None, None)

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

        connection.request("POST", '/wsman', headers=headers)
        response = connection.getresponse()
        response.read()
        if response.status != 401:
            raise HyperVAuthFailed("NTLM negotiation failed")

        auth_header = response.getheader("WWW-Authenticate", "")
        if auth_header == "":
            raise HyperVAuthFailed("NTLM negotiation failed")

        nego, challenge = auth_header.split(" ")
        if nego != "Negotiate":
            self.logger.warning("Wrong header: %s", auth_header)
            raise HyperVAuthFailed("Wrong header: %s", auth_header)

        nonce, flags = ntlm.parse_NTLM_CHALLENGE_MESSAGE(challenge)
        headers["Authorization"] = "Negotiate %s" % ntlm.create_NTLM_AUTHENTICATE_MESSAGE(
                    nonce, self.username, self.domainname, self.password, flags)

        connection.request("POST", '/wsman', headers=headers)
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
        hypervsoap = HyperVSoap(self.url, connection, headers, self.logger)
        try:
            if not self.useNewApi:
                # SettingType == 3 means current setting, 5 is snapshot - we don't want snapshots
                uuid = hypervsoap.Enumerate(
                    "select BIOSGUID, ElementName "
                    "from Msvm_VirtualSystemSettingData "
                    "where SettingType = 3",
                    "root/virtualization")
            else:
                # Filter out Planned VMs and snapshots, see
                # http://msdn.microsoft.com/en-us/library/hh850257%28v=vs.85%29.aspx
                uuid = hypervsoap.Enumerate(
                    "select BIOSGUID, ElementName "
                    "from Msvm_VirtualSystemSettingData "
                    "where VirtualSystemType = 'Microsoft:Hyper-V:System:Realized'",
                    "root/virtualization/v2")
        except HyperVException:
            if not self.useNewApi:
                self.logger.debug("Error when enumerating using root/virtualization namespace, "
                                  "trying root/virtualization/v2 namespace")
                self.useNewApi = True
                return self.getHostGuestMapping()
            raise

        # Get guest states
        guest_states = hypervsoap.Invoke_GetSummaryInformation(
                "root/virtualization/v2" if self.useNewApi else "root/virtualization")

        for instance in hypervsoap.Pull(uuid):
            try:
                uuid = instance["BIOSGUID"]
            except KeyError:
                self.logger.warning("Guest without BIOSGUID found, ignoring")
                continue

            try:
                elementName = instance["ElementName"]
            except KeyError:
                self.logger.warning("Guest %s is missing ElementName", uuid)
                continue

            try:
                state = guest_states[elementName]
            except KeyError:
                self.logger.warning("Unknown state for guest %s", elementName)
                state = virt.Guest.STATE_UNKNOWN

            guests.append(
                virt.Guest(
                    HyperV.decodeWinUUID(uuid),
                    self,
                    state,
                    hypervisorType='hyperv'))
        # Get the hostname
        hostname = None
        data = hypervsoap.Enumerate("select DNSHostName from Win32_ComputerSystem", "root/cimv2")
        for instance in hypervsoap.Pull(data, "root/cimv2"):
            hostname = instance["DNSHostName"]

        if self.config.hypervisor_id == 'uuid':
            uuid = hypervsoap.Enumerate("select UUID from Win32_ComputerSystemProduct", "root/cimv2")
            host = None
            for instance in hypervsoap.Pull(uuid, "root/cimv2"):
                host = HyperV.decodeWinUUID(instance["UUID"])
        elif self.config.hypervisor_id == 'hostname':
            host = hostname
        else:
            raise virt.VirtError('Reporting of hypervisor %s is not implemented in %s backend' %
                                 (self.config.hypervisor_id, self.CONFIG_TYPE))
        hypervisor = virt.Hypervisor(hypervisorId=host, name=hostname, guestIds=guests)
        return {'hypervisors': [hypervisor]}

    def ping(self):
        return True

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print "Usage: %s url username password"
        sys.exit(0)

    import logging
    logger = logging.Logger("virtwho.hyperv.main")
    logger.addHandler(logging.StreamHandler())
    from config import Config
    config = Config('test', 'hyperv', server=sys.argv[1], username=sys.argv[2],
                    password=sys.argv[3])
    hyperv = HyperV(logger, config)
    print dict((host, [guest.toDict() for guest in guests]) for host, guests in hyperv.getHostGuestMapping().items())
