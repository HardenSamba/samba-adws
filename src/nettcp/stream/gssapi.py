#!/usr/bin/env python2
# encoding: utf-8
# Copyright 2016 Timo Schmid
from __future__ import print_function, unicode_literals, absolute_import

import logging
import gssapi
from .negotiate import NegotiateStream

log = logging.getLogger(__name__ + '.GSSAPIStream')

# Plaintext chunk size fed to GSS wrap/encrypt. Must leave enough headroom
# below the NegotiateStream frame cap (0xFC30) for the GSS token overhead
# (Kerberos AES CFX header + confounder + duplicate header + HMAC ~ 60 bytes),
# otherwise a single wrapped token spills into a second frame and the reader,
# which assumes one frame == one token, fails to unwrap it.
_PLAINTEXT_CHUNK = 0xF000
_SPNEGO_OID = '1.3.6.1.5.5.2'
_REQUIRED_FLAGS = (
    gssapi.RequirementFlag.mutual_authentication,
    gssapi.RequirementFlag.confidentiality,
    gssapi.RequirementFlag.integrity,
    gssapi.RequirementFlag.replay_detection,
    gssapi.RequirementFlag.out_of_sequence_detection,
)
_DEFAULT_FLAGS = 0
for _flag in _REQUIRED_FLAGS:
    _DEFAULT_FLAGS |= _flag


class GSSAPIStream:
    def __init__(self, stream, server_name,
                 flags=_DEFAULT_FLAGS):
        self._inner = NegotiateStream(stream)
        if isinstance(server_name, str):
            server_name = gssapi.Name(server_name, name_type=gssapi.NameType.hostbased_service)
        self.server_name = server_name
        self.flags = flags
        self.client_ctx = None
        self._readcache = b''

    def negotiate(self):
        self.client_ctx = gssapi.SecurityContext(name=self.server_name, usage='initiate',
                                                 flags=self.flags,
                                                 mech=gssapi.OID.from_int_seq(_SPNEGO_OID))

        token = b''
        while not self.client_ctx.complete:
            log.debug('Doing step')
            token = self.client_ctx.step(token)

            if token:
                self._inner.write(token)
            if not self.client_ctx.complete:
                token = self._inner.read()
            else:
                log.debug('GSSAPI Handshake done')

        missing = [flag.name for flag in _REQUIRED_FLAGS
                   if flag not in self.client_ctx.actual_flags]
        if missing:
            raise IOError('GSSAPI context omitted required flags: %s' % ', '.join(missing))

    def write(self, data):
        if not self.client_ctx:
            self.negotiate()

        while data:
            data2 = data[:_PLAINTEXT_CHUNK]
            e_data = self.client_ctx.encrypt(data2)
            self._inner.write(e_data)
            data = data[_PLAINTEXT_CHUNK:]

    def read(self, count=None):
        if not self.client_ctx:
            self.negotiate()

        if count is None:
            sub = self._inner.read()
            return self.client_ctx.decrypt(sub)

        while len(self._readcache) < count:
            sub = self._inner.read()
            if not sub:
                raise IOError('connection closed mid-message')
            self._readcache += self.client_ctx.decrypt(sub)

        data = self._readcache[:count]
        self._readcache = self._readcache[count:]
        return data

    def close(self):
        self._inner.close()


class GENSECStream:
    def __init__(self, stream): #, server_name,
                 # flags=(gssapi.RequirementFlag.mutual_authentication |
                 #        gssapi.RequirementFlag.confidentiality |
                 #        gssapi.RequirementFlag.integrity)):
        from samba.param import LoadParm

        self._inner = NegotiateStream(stream)
        # if isinstance(server_name, str):
        #     server_name = gssapi.Name(server_name, name_type=gssapi.NameType.hostbased_service)
        # self.server_name = server_name
        # self.flags = flags
        self.client_ctx = None
        self._readcache = b''

        self.settings = {}

        self.settings["lp_ctx"] = self.lp_ctx = LoadParm()
        self.lp_ctx.load_default()

        self.settings["target_hostname"] = self.lp_ctx.get("netbios name")

    def negotiate_server(self):
        from samba import auth, gensec
        from samba.credentials import Credentials

        token = self._inner.read()

        self.client_ctx = gensec.Security.start_server(settings=self.settings,
                auth_context=auth.AuthContext(lp_ctx=self.lp_ctx))
        # gssapi.SecurityContext(name=self.server_name, usage='initiate',
                          #                       flags=self.flags)


        creds = Credentials()
        creds.guess(self.lp_ctx)
        creds.set_machine_account(self.lp_ctx)
        self.client_ctx.set_credentials(creds)

        self.client_ctx.start_mech_by_name("spnego")

        # token = b''

        server_finished = False
        while not server_finished:
            log.debug('Doing step')
            server_finished, server_to_client = self.client_ctx.update(token)

            if server_finished:
                log.debug('GSSAPI Handshake done')
                self._inner.write_handshake_done(server_to_client)
            else:
                self._inner.write(server_to_client)
                token = self._inner.read()

        # while not self.client_ctx.complete:
        #     log.debug('Doing step')
        #     token = self.client_ctx.step(token)
        #
        #     self._inner.write(token)
        #     if not self.client_ctx.complete:
        #         token = self._inner.read()
        #     else:
        #         log.debug('GSSAPI Handshake done')

    def write(self, data):
        if not self.client_ctx:
            self.negotiate()

        while data:
            data2 = data[:_PLAINTEXT_CHUNK]
            e_data = self.client_ctx.wrap(data2)
            self._inner.write(e_data)
            data = data[_PLAINTEXT_CHUNK:]

    def read(self, count=None):
        if not self.client_ctx:
            self.negotiate()

        if count is None:
            sub = self._inner.read()
            return self.client_ctx.unwrap(sub)

        while len(self._readcache) < count:
            sub = self._inner.read()
            if not sub:
                raise IOError('connection closed mid-message')
            self._readcache += self.client_ctx.unwrap(sub)

        data = self._readcache[:count]
        self._readcache = self._readcache[count:]
        return data

    def close(self):
        self._inner.close()
