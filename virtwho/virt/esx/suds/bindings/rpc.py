# This program is free software; you can redistribute it and/or modify it under
# the terms of the (LGPL) GNU Lesser General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Library Lesser General Public License
# for more details at ( http://www.gnu.org/licenses/lgpl.html ).
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
# written by: Jeff Ortel ( jortel@redhat.com )

"""
Classes for the (WS) SOAP I{rpc/literal} and I{rpc/encoded} bindings.

"""

from virtwho.virt.esx.suds import *
from virtwho.virt.esx.suds.mx.encoded import Encoded as MxEncoded
from virtwho.virt.esx.suds.umx.encoded import Encoded as UmxEncoded
from virtwho.virt.esx.suds.bindings.binding import Binding, envns
from virtwho.virt.esx.suds.sax.element import Element


encns = ("SOAP-ENC", "http://schemas.xmlsoap.org/soap/encoding/")


class RPC(Binding):
    """RPC/Literal binding style."""

    def param_defs(self, method):
        return self.bodypart_types(method)

    def envelope(self, header, body):
        env = super(RPC, self).envelope(header, body)
        env.addPrefix(encns[0], encns[1])
        env.set("%s:encodingStyle" % (envns[0],), encns[1])
        return env

    def bodycontent(self, method, args, kwargs):
        n = 0
        root = self.method(method)
        for pd in self.param_defs(method):
            if n < len(args):
                value = args[n]
            else:
                value = kwargs.get(pd[0])
            p = self.mkparam(method, pd, value)
            if p is not None:
                root.append(p)
            n += 1
        return root

    def replycontent(self, method, body):
        return body[0].children

    def method(self, method):
        """
        Get the document root. For I{rpc/(literal|encoded)}, this is the name
        of the method qualified by the schema tns.

        @param method: A service method.
        @type method: I{service.Method}
        @return: A root element.
        @rtype: L{Element}

        """
        ns = method.soap.input.body.namespace
        if ns[0] is None:
            ns = ('ns0', ns[1])
        return Element(method.name, ns=ns)


class Encoded(RPC):
    """RPC/Encoded (section 5) binding style."""

    def marshaller(self):
        return MxEncoded(self.schema())

    def unmarshaller(self):
        """
        Get the appropriate schema based XML decoder.

        @return: Typed unmarshaller.
        @rtype: L{UmxTyped}

        """
        return UmxEncoded(self.schema())
