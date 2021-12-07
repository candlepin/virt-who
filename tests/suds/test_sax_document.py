# -*- coding: utf-8 -*-

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
# written by: Jurko Gospodnetić ( jurko.gospodnetic@pke.hr )

"""
Suds SAX Document unit tests.

Implemented using the 'pytest' testing framework.

"""

if __name__ == "__main__":
    import testutils
    testutils.run_using_pytest(globals())

import virtwho.virt.esx.suds
from virtwho.virt.esx.suds.sax.document import Document
import virtwho.virt.esx.suds.sax.parser

import pytest

import re
import sys


class TestStringRepresentation:

    @staticmethod
    def create_test_document():
        input_data = virtwho.virt.esx.suds.byte_str("""\
<xsd:element name="ZuZu">
   <xsd:simpleType>
      <xsd:restriction base="xsd:string">
         <xsd:enumeration value="alfa"/>
         <xsd:enumeration value="beta"/>
         <xsd:enumeration value="gamma"/>
      </xsd:restriction>
   </xsd:simpleType>
</xsd:element>""")
        document = virtwho.virt.esx.suds.sax.parser.Parser().parse(virtwho.virt.esx.suds.BytesIO(input_data))
        assert document.__class__ is Document
        return document

    def test_convert_to_unicode(self):
        document = self.create_test_document()
        expected = document.str()
        assert str(document) == expected

    def test_plain_method(self):
        document = self.create_test_document()
        expected = Document.DECL + document.root().plain()
        result = document.plain()
        assert result == expected

    def test_str_method(self):
        document = self.create_test_document()
        expected = Document.DECL + "\n" + document.root().str()
        result = document.str()
        assert result == expected

    def test_xml_declaration(self):
        assert Document.DECL == '<?xml version="1.0" encoding="UTF-8"?>'
