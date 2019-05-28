import os
import subprocess

from tito.distributionbuilder import DistributionBuilder
from tito.common import info_out

class ScriptBuilder(DistributionBuilder):
    """Builder that also runs a script to produce one or more additional tarballs.
    This Builder looks for lines ending in '.tar.gz' in the output of the script, and treats
    those as artifacts of the script.
    """
    def __init__(self, config=None, *args, **kwargs):
        super(ScriptBuilder, self).__init__(config=config, *args, **kwargs)


    def tgz(self):
        retval = DistributionBuilder.tgz(self)
        self.sources.append(os.path.join(self.rpmbuild_basedir, 'build-rpm-no-ahv.patch'))
        self.artifacts.append(os.path.join(self.rpmbuild_basedir, 'build-rpm-no-ahv.patch'))
        subprocess.check_call("cp %s %s/" % ('build-rpm-no-ahv.patch', self.rpmbuild_sourcedir), shell=True)

        print(self.sources)
        return retval

