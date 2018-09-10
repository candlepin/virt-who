# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import
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

import re
from six.moves import urllib
import base64
import struct
from xml.etree import ElementTree
from requests.auth import AuthBase
import requests

from virtwho import virt
from . import ntlm
from virtwho.config import VirtConfigSection

try:
    from uuid import uuid1
except ImportError:
    import subprocess

    def uuid1():
        # fallback to calling commandline uuidgen
        return subprocess.Popen(["uuidgen"], stdout=subprocess.PIPE).communicate()[0].strip()


class HypervConfigSection(VirtConfigSection):
    """
    This class is used for validation of Hyper-V virtualization backend
    section. It tries to validate options and combination of options that
    are specific for this virtualization backend.
    """

    VIRT_TYPE = 'hyperv'
    HYPERVISOR_ID = ('uuid', 'hostname')

    def __init__(self, section_name, wrapper, *args, **kwargs):
        super(HypervConfigSection, self).__init__(section_name, wrapper, *args, **kwargs)
        self.add_key('server', validation_method=self._validate_server, required=True)
        self.add_key('username', validation_method=self._validate_username, required=True)
        self.add_key('password', validation_method=self._validate_unencrypted_password, required=True)

    def _validate_server(self, key):
        url_altered = False

        result = []
        if key not in self._values:
            self._values[key] = ''
        else:
            url = self._values[key]

            if "//" not in url:
                url_altered = True
                url = "//" + url
            parsed = urllib.parse.urlsplit(url, "http")
            if ":" not in parsed[1]:
                url_altered = True
                if parsed[0] == "https":
                    self.host = parsed[1] + ":5986"
                else:
                    self.host = parsed[1] + ":5985"
            else:
                self.host = parsed[1]
            if parsed[2] == "":
                url_altered = True
                path = "wsman"
            else:
                path = parsed[2]
            self.url = urllib.parse.urlunsplit((parsed[0], self.host, path, "", ""))
            self._values['url'] = self.url
            if url_altered:
                result.append((
                    'info',
                    "The original server URL was incomplete. It has been enhanced to %s" % self.url
                ))
        if len(result) == 0:
            return None
        else:
            return result


class HyperVAuth(AuthBase):
    def __init__(self, username, password, logger):
        self.username = username
        self.password = password
        self.logger = logger
        self.authenticated = False
        self.ignore_ntlm = False
        self.num_401s = 0
        self.ntlm = None
        self.basic = None

    def prepare_resend(self, response):
        '''
        Consume content and release the original connection
        to allow our new request to reuse the same one.
        '''
        response.content
        response.raw.release_conn()
        return response.request.copy()

    def retry_ntlm_negotiate(self, response, **kwargs):
        self.logger.debug("Using NTLM authentication")

        request = self.prepare_resend(response)

        self.ntlm = ntlm.Ntlm()
        negotiate = base64.b64encode(self.ntlm.negotiate_message(self.username)).decode('utf-8')
        request.headers["Authorization"] = "Negotiate %s" % negotiate
        r = response.connection.send(request, **kwargs)
        if r.status_code != 401:
            raise HyperVAuthFailed("NTLM authentication failed, unexpected error code %d" % r.status_code)
        return self.retry_ntlm_authenticate(r, **kwargs)

    def retry_ntlm_authenticate(self, response, **kwargs):
        self.logger.debug("Sending NTLM authentication data")

        request = self.prepare_resend(response)

        auth_header = response.headers.get("www-authenticate", '')
        nego, challenge = auth_header.split(" ", 1)
        if nego != "Negotiate":
            self.logger.warning("Wrong ntlm header: %s", auth_header)

        negotiate = base64.b64encode(self.ntlm.authentication_message(base64.b64decode(challenge), self.password))
        negotiate = negotiate.decode('utf-8')
        request.headers["Authorization"] = "Negotiate %s" % negotiate

        # Encrypt body of original request and include it
        request.body = self._body
        request.headers['Content-Length'] = len(self._body)

        self.encrypt_request(request)

        r = response.connection.send(request, **kwargs)
        if r.status_code == 401:
            raise HyperVAuthFailed("Incorrect domain/username/password")
        else:
            self.authenticated = True
            self.logger.debug("NTLM authentication successful")

        return self.decrypt_response(r)

    def encrypt_request(self, request):
        # Seal the message
        encrypted, signature = self.ntlm.encrypt(request.body)

        boundary = 'Encrypted Boundary'
        body = '''--{boundary}\r
Content-Type: application/HTTP-SPNEGO-session-encrypted\r
OriginalContent: type={original};Length={length}\r
--{boundary}\r
Content-Type: application/octet-stream\r
'''.format(
            original=request.headers["Content-Type"],
            length=len(encrypted),
            boundary=boundary)
        header_len = struct.pack('<I', len(signature))
        bin_body = body.encode('utf-8') + header_len + signature + encrypted
        bin_body += '--{boundary}--\r\n'.format(boundary=boundary).encode('utf-8')
        request.headers["Content-Type"] = (
            'multipart/encrypted;'
            'protocol="application/HTTP-SPNEGO-session-encrypted";'
            'boundary="{boundary}"').format(boundary=boundary)
        request.body = bin_body
        request.headers["Content-Length"] = len(bin_body)
        return request

    def decrypt_response(self, response):
        # See `encrypt_request` method for format of the response
        content_type = response.headers.get('Content-Type', 'text/xml')
        if 'multipart/encrypted' not in content_type:
            # The response is not encrypted, just return it
            return response
        data = response.raw.read(int(response.headers.get('Content-Length', 0))).decode('latin1')
        parts = re.split(r'-- ?Encrypted Boundary', data)
        try:
            body = parts[2].lstrip('\r\n').split('\r\n', 1)[1]
        except IndexError:
            self.logger.debug("Incorrect multipart data: %s", data)
            raise HyperVAuthFailed("Unable to decrypt sealed response: incorrect format")
        body = body.encode('latin1')
        # First four bytes of body is signature length
        l = struct.unpack('<I', body[:4])[0]
        # Then there is signature with given length
        signature = body[4:4 + l]
        # Message body follows
        msg = body[4 + l:]
        # Decrypt it
        decrypted = self.ntlm.decrypt(msg, signature)
        response._content = decrypted
        return response

    def retry_basic(self, response, **kwargs):
        self.logger.debug("Using Basic authentication")

        request = self.prepare_resend(response)

        passphrase = '%s:%s' % (self.username, self.password)
        self.basic = 'Basic %s' % base64.b64encode(passphrase).decode('utf-8')
        request.headers['Authorization'] = self.basic
        request.headers['Content-Length'] = len(self._body)
        request.body = self._body
        r = response.connection.send(request, **kwargs)
        if r.status_code == requests.codes.ok:
            self.authenticated = True
        return r

    def handle_response(self, response, **kwargs):
        if self.authenticated and self.ntlm:
            # If we're authenticated and have ntlm object, the body might be sealed
            return self.decrypt_response(response)
        if response.status_code == requests.codes.ok and not self.authenticated:
            self.authenticated = True
            response.request.body = self._body
            r = response.connection.send(response.request, **kwargs)
            return r

        if response.status_code == 401:
            authenticate_header = response.headers.get('www-authenticate', '').lower()
            if 'negotiate' in authenticate_header and not self.ignore_ntlm:
                return self.retry_ntlm_negotiate(response, **kwargs)
            elif 'basic' in authenticate_header:
                return self.retry_basic(response, **kwargs)
            else:
                raise HyperVAuthFailed(
                    "Server doesn't known any supported authentication method "
                    "(server methods: %s)" % authenticate_header)
        return response

    def __call__(self, request):
        request.headers["Connection"] = "Keep-Alive"
        if not self.authenticated:
            request.headers["Content-Length"] = "0"
            self._body = request.body
            request.body = None
            request.register_hook('response', self.handle_response)
        elif self.ntlm:
            request.register_hook('response', self.handle_response)
            return self.encrypt_request(request)
        elif self.basic:
            request.headers['Authorization'] = self.basic
        return request


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
    def __init__(self, url, connection, logger):
        self.url = url
        self.connection = connection
        self.generator = HyperVSoapGenerator(self.url)
        self.logger = logger

    def post(self, body):
        headers = {
            "Content-Type": "application/soap+xml;charset=UTF-8"
        }
        try:
            response = self.connection.post(self.url, body, headers=headers)
        except requests.RequestException as e:
            raise HyperVException("Unable to connect to Hyper-V server: %s" % str(e))

        if response.status_code == requests.codes.ok:
            return response.content
        elif response.status_code == 401:
            raise HyperVAuthFailed("Authentication failed")
        else:
            data = response.content
            try:
                xml_doc = ElementTree.fromstring(data)
                errorcode = xml_doc.find('.//{http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/MSFT_WmiError}error_Code')
                # Suppress reporting of invalid namespace, because we're testing
                # both old and new namespaces that HyperV uses
                if errorcode is None or errorcode.text != '2150858778':
                    title = xml_doc.find('.//title')
                    self.logger.debug("Invalid response (%d) from Hyper-V: %s", response.status_code, title.text)
            except Exception:
                self.logger.debug("Invalid response (%d) from Hyper-V", response.status_code)

            raise HyperVCallFailed("Communication with Hyper-V failed, HTTP error: %d" % response.status_code)

    @classmethod
    def _Instance(cls, xml_doc):
        def stripNamespace(tag):
            return tag[tag.find("}") + 1:]
        children = xml_doc.getchildren()
        if len(children) < 1:
            return None
        child = children[0]
        properties = {}
        for ch in child.getchildren():
            properties[stripNamespace(ch.tag)] = ch.text
        return properties

    def Enumerate(self, query, namespace="root/virtualization"):
        data = self.generator.enumerateXML(query=query, namespace=namespace)
        body = self.post(data)
        xml_doc = ElementTree.fromstring(body)
        if xml_doc.tag != "{%(s)s}Envelope" % self.generator.namespaces:
            raise HyperVException("Wrong reply format")
        responses = xml_doc.findall("{%(s)s}Body/{%(wsen)s}EnumerateResponse" % self.generator.namespaces)
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
        body = self.post(data)
        xml_doc = ElementTree.fromstring(body)
        if xml_doc.tag != "{%(s)s}Envelope" % self.generator.namespaces:
            raise HyperVException("Wrong reply format")
        responses = xml_doc.findall("{%(s)s}Body/{%(wsen)s}PullResponse" % self.generator.namespaces)
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
        body = self.post(data)
        xml_doc = ElementTree.fromstring(body)
        if xml_doc.tag != "{%(s)s}Envelope" % self.generator.namespaces:
            raise HyperVException("Wrong reply format")
        responses = xml_doc.findall("{%(s)s}Body/{%(vsms)s}GetSummaryInformation_OUTPUT" % {
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


class HyperVCallFailed(HyperVException):
    pass


class HyperV(virt.Virt):
    CONFIG_TYPE = "hyperv"

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(HyperV, self).__init__(logger, config, dest,
                                     terminate_event=terminate_event,
                                     interval=interval,
                                     oneshot=oneshot)
        self.url = self.config['url']
        self.username = self.config['username']
        self.password = self.config['password']

        # First try to use old API (root/virtualization namespace) if doesn't
        # work, go with root/virtualization/v2
        self.useNewApi = False

    def connect(self):
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1)
        s.mount('http://', adapter)
        s.auth = HyperVAuth(self.username, self.password, self.logger)
        return s

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

    def getVmmsVersion(self, hypervsoap):
        """
        This method retrieves the version of the vmms executable as it is the authoritative
        version of hyper-v running on the machine.

        https://social.technet.microsoft.com/Forums/windowsserver/en-US/dce2a4ec-10de-4eba-a19d-ae5213a2382d/how-to-tell-version-of-hyperv-installed?forum=winserverhyperv
        """
        vmmsVersion = ""
        data = hypervsoap.Enumerate("select * from CIM_Datafile where Path = '\\\\windows\\\\system32\\\\' and FileName='vmms'", "root/cimv2")
        for instance in hypervsoap.Pull(data, "root/cimv2"):
            if instance['Path'] == '\\windows\\system32\\':
                vmmsVersion = instance['Version']
        return vmmsVersion

    def getHostGuestMapping(self):
        guests = []
        connection = self.connect()
        hypervsoap = HyperVSoap(self.url, connection, self.logger)
        uuid = None
        if not self.useNewApi:
            try:
                # SettingType == 3 means current setting, 5 is snapshot - we don't want snapshots
                uuid = hypervsoap.Enumerate(
                    "select BIOSGUID, ElementName "
                    "from Msvm_VirtualSystemSettingData "
                    "where SettingType = 3",
                    "root/virtualization")
            except HyperVCallFailed:
                self.logger.debug("Unable to enumerate using root/virtualization namespace, "
                                  "trying root/virtualization/v2 namespace")
                self.useNewApi = True

        if self.useNewApi:
            # Filter out Planned VMs and snapshots, see
            # http://msdn.microsoft.com/en-us/library/hh850257%28v=vs.85%29.aspx
            uuid = hypervsoap.Enumerate(
                "select BIOSGUID, ElementName "
                "from Msvm_VirtualSystemSettingData "
                "where VirtualSystemType = 'Microsoft:Hyper-V:System:Realized'",
                "root/virtualization/v2")

        # Get guest states
        guest_states = hypervsoap.Invoke_GetSummaryInformation(
            "root/virtualization/v2" if self.useNewApi else "root/virtualization")
        vmmsVersion = self.getVmmsVersion(hypervsoap)
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

            guests.append(virt.Guest(HyperV.decodeWinUUID(uuid), self.CONFIG_TYPE, state))
        # Get the hostname
        hostname = None
        socket_count = None
        data = hypervsoap.Enumerate("select DNSHostName, NumberOfProcessors from Win32_ComputerSystem", "root/cimv2")
        for instance in hypervsoap.Pull(data, "root/cimv2"):
            hostname = instance["DNSHostName"]
            socket_count = instance["NumberOfProcessors"]

        if self.config['hypervisor_id'] == 'uuid':
            uuid = hypervsoap.Enumerate("select UUID from Win32_ComputerSystemProduct", "root/cimv2")
            host = None
            for instance in hypervsoap.Pull(uuid, "root/cimv2"):
                host = HyperV.decodeWinUUID(instance["UUID"])
        elif self.config['hypervisor_id'] == 'hostname':
            host = hostname
        facts = {
            virt.Hypervisor.CPU_SOCKET_FACT: str(socket_count),
            virt.Hypervisor.HYPERVISOR_TYPE_FACT: 'hyperv',
            virt.Hypervisor.HYPERVISOR_VERSION_FACT: vmmsVersion,
        }
        hypervisor = virt.Hypervisor(hypervisorId=host, name=hostname, guestIds=guests, facts=facts)
        return {'hypervisors': [hypervisor]}

    def ping(self):
        return True
