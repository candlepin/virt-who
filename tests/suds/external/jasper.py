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

import sys
sys.path.append('../../')

from virtwho.virt.esx.suds import WebFault
from virtwho.virt.esx.suds.client import Client

import traceback as tb


errors = 0


def start(url):
    print('\n______________________________________________________________\n')
    print('Test @ ( %s )' % (url,))

try:
    url = 'http://localhost:9090/jasperserver-pro/services/repository?wsdl'
    start(url)
    client = Client(url, username='jeff', password='ortel')
    print(client)
    print(client.service.list(''))
except WebFault, f:
    errors += 1
    print(f)
    print(f.fault)
except (KeyboardInterrupt, SystemExit):
    raise
except Exception:
    errors += 1
    print(sys.exc_info()[1])
    tb.print_exc()

print('\nFinished: errors = %d' % (errors,))