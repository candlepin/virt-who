from __future__ import print_function

from binascii import unhexlify
from base import TestBase

from virtwho.virt.hyperv.ntlm import (ntowfv2, ntlm_compute_response, Ntlm,
                                      ChallengeMessage, AuthenticationMessage)


def from_hex(hexStr):
    return unhexlify(hexStr.replace(' ', ''))


def to_hex_lines(s):
    lines = []
    for i in range(0, len(s), 8):
        part = s[i:i + 8]
        line = ' '.join('{:02X}'.format(ord(x) if not isinstance(x, int) else x) for x in part)
        lines.append(line)
    return lines


class TestNtlm(object):
    ''' Test of NTLM authentication and encryption. '''

    def assertHexEqual(self, h1, h2):
        diffs = []
        has_error = False
        hex1 = to_hex_lines(h1)
        hex2 = to_hex_lines(h2)
        for i, line1, line2 in zip(range(len(hex1)), hex1, hex2):
            if line1 != line2:
                diffs.append("Bytes %d - %d differs:   %s != %s" % (i, i + 15, line1, line2))
                has_error = True
            else:
                diffs.append("Bytes %d - %d are equal: %s == %s" % (i, i + 15, line1, line2))
        if has_error:
            raise AssertionError('\n' + '\n'.join(diffs))

    def test_example_data(self):
        '''
        There are example values in the specification.
        We use them to test our implementation.
        '''
        user = 'User'
        domain = 'Domain'
        password = 'Password'
        workstation = 'COMPUTER'
        time = b'\x00' * 8
        client_challenge = from_hex('aa aa aa aa aa aa aa aa')
        server_challenge = from_hex('01 23 45 67 89 ab cd ef')
        target_info = from_hex('02 00 0c 00 44 00 6f 00 6d 00 61 00 69 00 6e 00 '
                               '01 00 0c 00 53 00 65 00 72 00 76 00 65 00 72 00 '
                               '00 00 00 00')
        flags = b'\x33\x82\x0A\x82'

        response_key_nt = response_key_lm = ntowfv2(password, user, domain)
        self.assertHexEqual(
            response_key_nt,
            from_hex('0c 86 8a 40 3b fd 7a 93 a3 00 1e f2 2e f0 2e 3f'))

        nt_challenge_response, lm_challenge_response, session_base_key = ntlm_compute_response(
            flags, response_key_nt, response_key_lm,
            server_challenge, client_challenge, time, target_info)

        self.assertHexEqual(
            # The value is somehow truncated in the NTMP document
            nt_challenge_response[:16],
            from_hex('68 cd 0a b8 51 e5 1c 96 aa bc 92 7b eb ef 6a 1c'))

        self.assertHexEqual(
            lm_challenge_response,
            from_hex('86 c3 50 97 ac 9c ec 10 25 54 76 4a 57 cc cc 19 '
                     'aa aa aa aa aa aa aa aa'))

        self.assertHexEqual(
            session_base_key,
            from_hex('8d e4 0c ca db c1 4a 82 f1 5c b0 ad 0d e9 5c a3'))

        challenge = from_hex(
            '4e 54 4c 4d 53 53 50 00 02 00 00 00 0c 00 0c 00 '
            '38 00 00 00 33 82 8a e2 01 23 45 67 89 ab cd ef '
            '00 00 00 00 00 00 00 00 24 00 24 00 44 00 00 00 '
            '06 00 70 17 00 00 00 0f 53 00 65 00 72 00 76 00 '
            '65 00 72 00 02 00 0c 00 44 00 6f 00 6d 00 61 00 '
            '69 00 6e 00 01 00 0c 00 53 00 65 00 72 00 76 00 '
            '65 00 72 00 00 00 00 00'
        )
        challenge_message = ChallengeMessage(challenge)

        authenticate = from_hex(
            '4e 54 4c 4d 53 53 50 00 03 00 00 00 18 00 18 00 '
            '6c 00 00 00 54 00 54 00 84 00 00 00 0c 00 0c 00 '
            '48 00 00 00 08 00 08 00 54 00 00 00 10 00 10 00 '
            '5c 00 00 00 10 00 10 00 d8 00 00 00 35 82 88 e2 '
            '05 01 28 0a 00 00 00 0f 44 00 6f 00 6d 00 61 00 '
            '69 00 6e 00 55 00 73 00 65 00 72 00 43 00 4f 00 '
            '4d 00 50 00 55 00 54 00 45 00 52 00 86 c3 50 97 '
            'ac 9c ec 10 25 54 76 4a 57 cc cc 19 aa aa aa aa '
            'aa aa aa aa 68 cd 0a b8 51 e5 1c 96 aa bc 92 7b '
            'eb ef 6a 1c 01 01 00 00 00 00 00 00 00 00 00 00 '
            '00 00 00 00 aa aa aa aa aa aa aa aa 00 00 00 00 '
            '02 00 0c 00 44 00 6f 00 6d 00 61 00 69 00 6e 00 '
            '01 00 0c 00 53 00 65 00 72 00 76 00 65 00 72 00 '
            '00 00 00 00 00 00 00 00 c5 da d2 54 4f c9 79 90 '
            '94 ce 1c e9 0b c9 d0 3e'
        )

        auth_message = AuthenticationMessage(
            user, password, domain, workstation, challenge_message.server_challenge,
            challenge_message.target_info, challenge_message.negotiate_flags,
            client_challenge=b'\xAA' * 8, exported_session_key=b'U' * 16)

        self.assertHexEqual(auth_message.data, authenticate)

        ntlm = Ntlm()
        ntlm.set_session_key(auth_message.session_key)

        self.assertHexEqual(
            ntlm.outgoing_sealing_key,
            from_hex('59 f6 00 97 3c c4 96 0a 25 48 0a 7c 19 6e 4c 58'))

        self.assertHexEqual(
            ntlm.outgoing_signing_key,
            from_hex('47 88 dc 86 1b 47 82 f3 5d 43 fd 98 fe 1a 2d 39'))

        encrypted, signature = ntlm.encrypt('Plaintext'.encode('utf-8'))
        self.assertHexEqual(
            encrypted,
            from_hex('54 89 0C 0C B0 6D 3A A4 83'))
        self.assertHexEqual(
            signature,
            from_hex('01 00 00 00 71 25 99 58 FA 90 2D B2 00 00 00 00'))
