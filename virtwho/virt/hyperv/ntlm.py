# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import six
import struct
from socket import gethostname
import hmac
import hashlib

if not six.PY3:
    from M2Crypto.RC4 import RC4
else:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    from cryptography.hazmat.backends import default_backend

    class RC4(object):
        def __init__(self, key):
            if isinstance(key, str):
                key = key.encode('utf-8')
            cipher = Cipher(algorithms.ARC4(key), mode=None, backend=default_backend())
            self.encrypter = cipher.encryptor()

        def update(self, message):
            if isinstance(message, str):
                message = message.encode('utf-8')
            return self.encrypter.update(message)


def rc4k(key, message):
    '''
    Compute rc4 of `message` with initial `key`.
    '''
    return RC4(key).update(message)


def mac(handle, signing_key, seq_num, message):
    '''
    MAC signing method that create signature for given `message` with sequence
    number `seq_num` and using key `signing_key`. The `handle` corresponds to
    current state of sealing key.
    '''
    if not isinstance(message, six.binary_type):
        message = message.encode('utf-8')
    hmac_md5 = hmac.new(signing_key, struct.pack('<I', seq_num) + message).digest()[:8]
    checksum = handle.update(hmac_md5)
    return struct.pack('<I8sI', 1, checksum[:8], seq_num)


def nonce(bytes):
    '''
    Random data with length of `bytes`.
    '''
    return os.urandom(bytes)


def ntlm_compute_response(flags, response_key_nt, response_key_lm,
                          server_challenge, client_challenge, time, target_info):
    '''
    Compute NTLMv2 response.

    Return tuple (nt_challenge_response, lm_challenge_response, session_base_key).
    '''
    responser_version = b'\x01'
    hi_responser_version = b'\x01'
    temp = (
        responser_version + hi_responser_version + b'\0' * 6 + time +
        client_challenge + b'\0' * 4 + target_info + b'\0' * 4
    )
    nt_proof_str = hmac.new(response_key_nt, server_challenge + temp).digest()
    nt_challenge_response = nt_proof_str + temp
    lm_challenge_response = hmac.new(response_key_lm, server_challenge + client_challenge).digest() + client_challenge
    session_base_key = hmac.new(response_key_nt, nt_proof_str).digest()
    return nt_challenge_response, lm_challenge_response, session_base_key


def ntowfv2(passwd, user, domain):
    '''
    Hash password `passwd` using `user` and `domain`.
    '''
    return hmac.new(
        hashlib.new('md4', passwd.encode('utf-16le')).digest(),
        (user.upper() + domain).encode('utf-16le')
    ).digest()


class NtlmError(Exception):
    pass


# Session keys for NTLM
SESSION_C2S_SEAL = b'session key to client-to-server sealing key magic constant\x00'
SESSION_S2C_SEAL = b'session key to server-to-client sealing key magic constant\x00'
SESSION_C2S_SIGN = b'session key to client-to-server signing key magic constant\x00'
SESSION_S2C_SIGN = b'session key to server-to-client signing key magic constant\x00'

# NTLM Flags
NTLM_NegotiateUnicode = 0x00000001
NTLM_NegotiateOEM = 0x00000002
NTLM_RequestTarget = 0x00000004
NTLM_Unknown9 = 0x00000008
NTLM_NegotiateSign = 0x00000010
NTLM_NegotiateSeal = 0x00000020
NTLM_NegotiateDatagram = 0x00000040
NTLM_NegotiateLanManagerKey = 0x00000080
NTLM_Unknown8 = 0x00000100
NTLM_NegotiateNTLM = 0x00000200
NTLM_NegotiateNTOnly = 0x00000400
NTLM_Anonymous = 0x00000800
NTLM_NegotiateOemDomainSupplied = 0x00001000
NTLM_NegotiateOemWorkstationSupplied = 0x00002000
NTLM_Unknown6 = 0x00004000
NTLM_NegotiateAlwaysSign = 0x00008000
NTLM_TargetTypeDomain = 0x00010000
NTLM_TargetTypeServer = 0x00020000
NTLM_TargetTypeShare = 0x00040000
NTLM_NegotiateExtendedSecurity = 0x00080000
NTLM_NegotiateIdentify = 0x00100000
NTLM_Unknown5 = 0x00200000
NTLM_RequestNonNTSessionKey = 0x00400000
NTLM_NegotiateTargetInfo = 0x00800000
NTLM_Unknown4 = 0x01000000
NTLM_NegotiateVersion = 0x02000000
NTLM_Unknown3 = 0x04000000
NTLM_Unknown2 = 0x08000000
NTLM_Unknown1 = 0x10000000
NTLM_Negotiate128 = 0x20000000
NTLM_NegotiateKeyExchange = 0x40000000
NTLM_Negotiate56 = 0x80000000


class Message(object):
    '''
    Abstract message for NTLM authentication.
    '''
    VERSION = [
        ('product_major_version', '<B'),
        ('product_minor_version', '<B'),
        ('product_build', '<H'),
        ('reserved', '<B'),
        ('reserved', '<B'),
        ('reserved', '<B'),
        ('ntlm_revision_current', '<B'),
    ]

    DEFAULTS = {
        'signature': b'NTLMSSP\0',
        'product_major_version': 5,
        'product_minor_version': 1,
        'product_build': 2600,
        'reserved': 0,
        'ntlm_revision_current': 15,
    }


class IncomingMessage(Message):
    '''
    Abstract incoming NTLM message.
    '''
    def __init__(self, message):
        self._items = {}
        self.payload = None
        self._parse(message)

    def _parse(self, message):
        offset = 0
        for name, signature in self.FORMAT:
            self._items[name] = struct.unpack_from(signature, message, offset)[0]
            offset += struct.calcsize(signature)
        self.payload = message[offset:]

    def __getattr__(self, name):
        try:
            return self._items[name]
        except KeyError:
            return Message.__getattr__(self, name)


class OutgoingMessage(Message):
    '''
    Abstract outgoing NTLM message.
    '''
    def __init__(self, params):
        self.params = params

    def _format(self):
        message = []
        for name, signature in self.FORMAT:
            item = self.params.get(name)
            if item is None:
                item = self.DEFAULTS[name]
            if 's' in signature and isinstance(item, str):
                item = item.encode('utf-8')
            message.append(struct.pack(signature, item))
        res = message[0]
        for item in message[1:]:
            res += item
        return res

    @property
    def data(self):
        return self._format()


class NegotiateMessage(OutgoingMessage):
    '''
    NegotiateMessage is first message (sent by client) to initiate NTLM auth.
    '''
    HEADER_LENGTH = 40
    FORMAT = [
        ('signature', '8s'),
        ('message_type', '<I'),
        ('negotiate_flags', '<I'),
        ('domain_name_len', '<H'),
        ('domain_name_len', '<H'),
        ('domain_name_buffer_offset', '<I'),
        ('workstation_len', '<H'),
        ('workstation_len', '<H'),
        ('workstation_buffer_offset', '<I'),
    ] + OutgoingMessage.VERSION
    DEFAULTS = OutgoingMessage.DEFAULTS.copy()
    DEFAULTS.update({
        'message_type': 0x00000001,
        'negotiate_flags': (
            NTLM_NegotiateUnicode |
            NTLM_NegotiateOEM |
            NTLM_RequestTarget |
            NTLM_NegotiateNTLM |
            NTLM_NegotiateOemWorkstationSupplied |
            NTLM_NegotiateAlwaysSign |
            NTLM_NegotiateSign |
            NTLM_NegotiateSeal |
            NTLM_NegotiateExtendedSecurity |
            NTLM_NegotiateVersion |
            NTLM_Negotiate128 |
            NTLM_Negotiate56 |
            NTLM_NegotiateKeyExchange
        ),
    })

    def __init__(self, domain, workstation, flags=None):
        self.domain = domain if not six.PY3 else domain.encode('ascii')
        self.workstation = workstation if not six.PY3 else workstation.encode('ascii')
        self.flags = flags

    def _format(self):
        domain_len = len(self.domain)
        domain_offset = self.HEADER_LENGTH
        workstation_len = len(self.workstation)
        workstation_offset = domain_offset + domain_len
        self.params = {
            'domain_name_len': domain_len,
            'domain_name_buffer_offset': domain_offset,
            'workstation_len': workstation_len,
            'workstation_buffer_offset': workstation_offset
        }
        if self.flags is not None:
            self.params['negotiate_flags'] = self.flags
        else:
            self.params['negotiate_flags'] = self.DEFAULTS['negotiate_flags']
        if domain_len > 0:
            self.params['negotiate_flags'] |= NTLM_NegotiateOemDomainSupplied
        return OutgoingMessage._format(self) + self.domain + self.workstation


class ChallengeMessage(IncomingMessage):
    '''
    ChallengeMessage is send by server to provide data for NTLM authentication
    and sealing.
    '''
    FORMAT = (
        ('signature', '8s'),
        ('message_type', '<I'),
        ('target_name_len', '<H'),
        ('target_name_len_max', '<H'),
        ('target_name_buffer_offset', '<I'),
        ('negotiate_flags', '<I'),
        ('server_challenge', '8s'),
        ('reserved', '8s'),
        ('target_info_len', '<H'),
        ('target_info_len_max', '<H'),
        ('target_info_buffer_offset', '<I'),
        ('version', '8s'),
        # Payload (variable)
    )

    def _parse(self, message):
        IncomingMessage._parse(self, message)
        assert self._items['signature'] == b'NTLMSSP\x00'
        assert self._items['message_type'] == 2
        self._items['target_name'] = message[
            self._items['target_name_buffer_offset']:
            self._items['target_name_buffer_offset'] + self._items['target_name_len']]
        self._items['target_info'] = message[
            self._items['target_info_buffer_offset']:
            self._items['target_info_buffer_offset'] + self._items['target_info_len']]
        flags = self._items['negotiate_flags']
        for flag in (NTLM_NegotiateUnicode, NTLM_NegotiateExtendedSecurity, NTLM_Negotiate128):
            if not flag & flags:
                raise NtlmError("NTLM negotiation failed, no flag %d" % flag)


class AuthenticationMessage(OutgoingMessage):
    '''
    AuthenticateMessage is final message that the client sends. It contains
    encrypted session key and other data used by authentication and sealing.
    '''
    HEADER_LENGTH = 72
    FORMAT = [
        ('signature', '8s'),
        ('message_type', '<I'),
        ('lm_challenge_response_len', '<H'),
        ('lm_challenge_response_len', '<H'),
        ('lm_challenge_response_buffer_offset', '<I'),
        ('nt_challenge_response_len', '<H'),
        ('nt_challenge_response_len', '<H'),
        ('nt_challenge_response_buffer_offset', '<I'),
        ('domain_name_len', '<H'),
        ('domain_name_len', '<H'),
        ('domain_name_buffer_offset', '<I'),
        ('user_name_len', '<H'),
        ('user_name_len', '<H'),
        ('user_name_buffer_offset', '<I'),
        ('workstation_len', '<H'),
        ('workstation_len', '<H'),
        ('workstation_buffer_offset', '<I'),
        ('encrypted_random_session_key_len', '<H'),
        ('encrypted_random_session_key_len', '<H'),
        ('encrypted_random_session_key_buffer_offset', '<I'),
        ('negotiate_flags', '<I'),
    ] + OutgoingMessage.VERSION
    DEFAULTS = OutgoingMessage.DEFAULTS.copy()
    DEFAULTS.update({
        'message_type': 0x00000003,
        'negotiate_flags': (
            NTLM_NegotiateKeyExchange |
            NTLM_Negotiate128 |
            NTLM_Negotiate56 |
            NTLM_NegotiateVersion |
            NTLM_NegotiateTargetInfo |
            NTLM_NegotiateExtendedSecurity |
            NTLM_NegotiateUnicode |
            NTLM_NegotiateSign |
            NTLM_NegotiateSeal |
            NTLM_NegotiateNTLM |
            NTLM_NegotiateAlwaysSign |
            NTLM_RequestTarget
        ),
    })

    def __init__(self, username, password, domain, workstation, server_challenge,
                 target_info, negotiate_flags, client_challenge=None,
                 exported_session_key=None):
        self.username = username
        self.password = password
        self.domain = domain
        self.workstation = workstation
        self.server_challenge = server_challenge
        self.target_info = target_info
        self.time = self._time_from_target_info(target_info)
        self.negotiate_flags = negotiate_flags
        if client_challenge is not None:
            self.client_challenge = client_challenge
        else:
            self.client_challenge = nonce(8)
        if exported_session_key is not None:
            self.exported_session_key = exported_session_key
        else:
            self.exported_session_key = nonce(16)

        self._compute_encryption_data()

    def _compute_encryption_data(self):
        '''
        Compute data that are needed for authentication and encryption.
        '''
        time = self.time or b'\0' * 8

        response_key_nt = response_key_lm = ntowfv2(self.password, self.username, self.domain)
        self.nt_challenge_response, self.lm_challenge_response, session_base_key = ntlm_compute_response(
            self.negotiate_flags, response_key_nt, response_key_lm,
            self.server_challenge, self.client_challenge, time, self.target_info)

        if self.time:
            # Send NULLs instead of lm_challenge_response if we have time from server
            self.lm_challenge_response = b'\0' * 24

        key_exchange_key = session_base_key  # key_exchange_key is always session_base_key in NTLMv2
        if self.negotiate_flags & NTLM_NegotiateKeyExchange:
            exported_session_key = self.exported_session_key
            self.encrypted_random_session_key = rc4k(key_exchange_key, exported_session_key)
        else:
            exported_session_key = key_exchange_key
            self.encrypted_random_session_key = ''

        # The NTLM_NegotiateExtendedSecurity flag is always set
        if NTLM_Negotiate128 & self.negotiate_flags:
            self.session_key = exported_session_key
        elif NTLM_Negotiate56 & self.negotiate_flags:
            self.session_key = exported_session_key[:7]
        else:
            self.session_key = exported_session_key[:4]

    def _time_from_target_info(self, target_info):
        '''
        Extract timestamp from target_info.
        '''
        l = len(target_info)
        offset = 0
        timestamp = None
        while offset < l:
            av_id = struct.unpack_from('<H', target_info, offset)[0]
            offset += 2
            av_len = struct.unpack_from('<H', target_info, offset)[0]
            offset += 2
            if av_id == 0x0007:  # Timestamp
                timestamp = target_info[offset:offset + av_len]
            offset += av_len
        return timestamp

    def _format(self):
        username = self.username.encode('utf-16-le')
        domain = self.domain.encode('utf-16-le')
        workstation = self.workstation.encode('utf-16-le')
        domain_len = len(domain)
        domain_offset = self.HEADER_LENGTH
        username_len = len(username)
        username_offset = domain_offset + domain_len
        workstation_len = len(workstation)
        workstation_offset = username_offset + username_len

        lm_challenge_response_len = len(self.lm_challenge_response)
        lm_challenge_response_offset = workstation_offset + workstation_len

        nt_challenge_response_len = len(self.nt_challenge_response)
        nt_challenge_response_offset = lm_challenge_response_offset + lm_challenge_response_len

        encrypted_random_session_key_len = len(self.encrypted_random_session_key)
        encrypted_random_session_key_offset = nt_challenge_response_offset + nt_challenge_response_len
        mic = b'\0' * 16

        flags = self.DEFAULTS['negotiate_flags']
        self.params = {
            'lm_challenge_response_len': lm_challenge_response_len,
            'lm_challenge_response_buffer_offset': lm_challenge_response_offset,
            'nt_challenge_response_len': nt_challenge_response_len,
            'nt_challenge_response_buffer_offset': nt_challenge_response_offset,
            'domain_name_len': domain_len,
            'domain_name_buffer_offset': domain_offset,
            'user_name_len': username_len,
            'user_name_buffer_offset': username_offset,
            'workstation_len': workstation_len,
            'workstation_buffer_offset': workstation_offset,
            'encrypted_random_session_key_len': encrypted_random_session_key_len,
            'encrypted_random_session_key_buffer_offset': encrypted_random_session_key_offset,
            'negotiate_flags': flags,
            'mic': mic,
        }
        return (
            OutgoingMessage._format(self) + domain + username + workstation +
            self.lm_challenge_response + self.nt_challenge_response +
            self.encrypted_random_session_key)


class Ntlm(object):
    '''
    Wrapper for NTLM authentication and sealing.

    Usage:
    First call `negotiate_message` to create message of type 1 to be send
    to server. Then server will respond with message of type 2. Supply it to
    `authentication_message` as `challenge` argument together with `password`.
    This method will return type 3 message that should be send to server
    together with (possibly encrypted) data.

    After these steps, you can encrypt and decrypt message using `encrypt`
    and `decrypt` methods.
    '''
    def __init__(self):
        self.incoming_seq_number = 0
        self.outgoing_seq_number = 0

    def negotiate_message(self, username):
        '''
        Create type 1 message to be send to server.
        '''
        user_parts = username.split('\\', 1)
        if len(user_parts) > 1:
            self.domain = user_parts[0].upper()
            self.username = user_parts[1]
        else:
            self.domain = ''
            self.username = username
        self.workstation = gethostname().upper()
        data = NegotiateMessage(self.domain, self.workstation).data
        return data

    def authentication_message(self, challenge, password):
        '''
        Create type 3 message from type 2 (`challenge` argument) and user
        `password`.
        '''
        challenge = ChallengeMessage(challenge)
        msg = AuthenticationMessage(
            self.username, password, self.domain, self.workstation,
            challenge.server_challenge, challenge.target_info,
            challenge.negotiate_flags)

        self.set_session_key(msg.session_key)
        return msg.data

    def set_session_key(self, session_key):
        '''
        Set session key that will be used for encryption and decryption.

        If you call `authentication_message` you don't need to call this method.
        '''
        self.session_key = session_key

        self.outgoing_sealing_key = hashlib.md5(session_key + SESSION_C2S_SEAL).digest()
        self.incoming_sealing_key = hashlib.md5(session_key + SESSION_S2C_SEAL).digest()
        self.outgoing_signing_key = hashlib.md5(session_key + SESSION_C2S_SIGN).digest()
        self.incoming_signing_key = hashlib.md5(session_key + SESSION_S2C_SIGN).digest()

        self.outgoing_seal_handle = RC4(self.outgoing_sealing_key)
        self.incoming_seal_handle = RC4(self.incoming_sealing_key)

    def encrypt(self, message):
        '''
        Encrypt and sign given `message` and return pair
        (encrypted_message, signature).
        '''
        sealed_message = self.outgoing_seal_handle.update(message)
        signature = mac(self.outgoing_seal_handle, self.outgoing_signing_key, self.outgoing_seq_number, message)
        self.outgoing_seq_number += 1
        return sealed_message, signature

    def decrypt(self, sealed_message, signature):
        '''
        Decrypt `sealed_message` and check it signature. Return decrypted
        message or Exception if sequence number or signature doesn't match.
        '''
        message = self.incoming_seal_handle.update(sealed_message)
        version, checksum, sequence = struct.unpack('<I8sI', signature)
        if sequence != self.incoming_seq_number:
            raise Exception("Incorrect sequence number")
        checksum = self.incoming_seal_handle.update(checksum)
        expected_checksum = hmac.new(
            self.incoming_signing_key,
            struct.pack('<I', self.incoming_seq_number) + message).digest()[:8]
        self.incoming_seq_number += 1
        if checksum != expected_checksum:
            raise Exception("Message has been altered")
        return message
