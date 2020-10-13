import os
import subprocess

from tito.distributionbuilder import DistributionBuilder
from tito.common import info_out

class PatchBuilder(DistributionBuilder):
    """Builder that includes a patch files in the tarball.
    """
    def __init__(self, config=None, *args, **kwargs):
        super(PatchBuilder, self).__init__(config=config, *args, **kwargs)


    def tgz(self):
        retval = DistributionBuilder.tgz(self)
        self.sources.append(os.path.join(self.rpmbuild_basedir, 'build-rpm-no-ahv.patch'))
        self.artifacts.append(os.path.join(self.rpmbuild_basedir, 'build-rpm-no-ahv.patch'))
        subprocess.check_call("cp %s %s/" % ('build-rpm-no-ahv.patch', self.rpmbuild_basedir), shell=True)

        return retval
