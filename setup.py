#!/usr/bin/python2

from __future__ import print_function
import sys
import os
import subprocess
from setuptools import setup, find_packages
from distutils.command.install import install
from distutils.command.build import build as _build
from distutils.command.build_py import build_py as _build_py
from shutil import copy, copyfileobj
import gzip


def install_file(filename, destination, file_mode=0o644, dir_mode=0o755):
    install_dir = os.path.dirname(destination)
    if not os.path.isdir(install_dir):
        os.makedirs(install_dir, dir_mode)
    copy(filename, destination)
    os.chmod(destination, file_mode)


class InstallSystemd(install):
    description = 'install systemd service'

    def run(self, *args, **kwargs):
        root = self.root or ''
        if self.prefix != '/usr':
            print("systemd service has to be installed to /usr")
            sys.exit(1)
        install_file('virt-who.service', '{root}/usr/lib/systemd/system/virt-who.service'.format(root=root))


class InstallUpstart(install):
    description = 'install upstart service'

    def run(self, *args, **kwargs):
        root = self.root or ''
        install_file('virt-who-initscript', '{root}/etc/rc.d/init.d/virt-who'.format(root=root), file_mode=0o755)


class InstallManPages(install):
    description = 'install manual pages'

    MAN_PAGES = (
        ('virt-who', '8'),
        ('virt-who-config', '5'),
        ('virt-who-password', '8'),
    )

    def run(self, *args, **kwargs):
        root = self.root or ''
        # gzip embeds output filename and it breaks rpmbuild
        # we need to use relative name
        old_wd = os.getcwd()
        os.chdir(root)
        for name, number in self.MAN_PAGES:
            filename = '{old_wd}/{name}.{number}'.format(old_wd=old_wd, name=name, number=number)
            dirname = 'usr/share/man/man{number}'.format(number=number)
            if not os.path.isdir(dirname):
                os.makedirs(dirname, 0o755)
            outfile = '{dirname}/{name}.{number}.gz'.format(
                dirname=dirname, name=name, number=number)

            with open(filename, 'rb') as f_in:
                # gzip in py26 doesn't support contextmanager
                f_out = gzip.open(outfile, 'wb')
                try:
                    copyfileobj(f_in, f_out)
                finally:
                    f_out.close()
        os.chdir(old_wd)


class InstallConfig(install):
    description = 'install configuration files'

    FILES = (
        ('virt-who.conf', '{root}/etc/sysconfig/virt-who'),
        ('template.conf', '{root}/etc/virt-who.d/template.conf'),
        ('template-general.conf', '{root}/etc/virt-who.conf'),
    )

    def run(self, *args, **kwargs):
        root = self.root or ''
        for origname, output in self.FILES:
            install_file(origname, output.format(root=root))


version = {}
with open('virtwho/version.py') as ver_file:
    exec(ver_file.read(), version)

# subclass build_py so we can generate
# version.py based on either args passed
# in (--rpm-version, --gtk-version) or
# from a guess generated from 'git describe'
class rpm_version_release_build_py(_build_py):
    user_options = _build_py.user_options + [
        ('rpm-version=', None, 'version and release of the RPM this is built for')]

    def initialize_options(self):
        _build_py.initialize_options(self)
        self.rpm_version = None
        self.versioned_packages = []
        self.git_tag_prefix = "virt-who-"

    def finalize_options(self):
        _build_py.finalize_options(self)
        self.set_undefined_options(
            'build',
            ('rpm_version', 'rpm_version')
        )

    def run(self):
        _build_py.run(self)
        # create a "version.py" that includes the rpm version
        # info passed to our new build_py args

        if not self.dry_run:
            for package in self.versioned_packages:
                version_dir = os.path.join(self.build_lib, package)
                version_file = os.path.join(version_dir, 'version.py')
                try:
                    lines = []
                    with open(version_file, 'r') as f:
                        for l in f.readlines():
                            l = l.replace("RPM_VERSION", str(self.rpm_version))
                            lines.append(l)

                    with open(version_file, 'w') as f:
                        for l in lines:
                            f.write(l)
                except EnvironmentError:
                    raise

class build(_build):
    user_options = _build.user_options + [
        ('rpm-version=', None, 'version and release of the RPM this is built for')
    ]
    def initialize_options(self):
        _build.initialize_options(self)
        self.rpm_version = None
        self.git_tag_prefix = "virt-who-"

    def finalize_options(self):
        _build.finalize_options(self)
        if not self.rpm_version:
            self.rpm_version = self.get_git_describe()

    def get_git_describe(self):
        try:
            cmd = ["git", "describe"]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
            output = process.communicate()[0].decode('utf-8').strip()
            if output.startswith(self.git_tag_prefix):
                return output[len(self.git_tag_prefix):]
        except OSError:
            # When building the RPM there won't be a git repo to introspect so
            # builders *must* specify the version via the --rpm-version option
            return "unknown"

setup(
    name='virt-who',
    version='0.29.1',
    description='virt-who is agent for reporting virtual guest IDs to subscription manager.',
    # long_description=open('README.md').read(),
    author='Radek Novacek',
    author_email='rnovacek@redhat.com',
    license='LICENSE',
    url='https://github.com/virt-who/virt-who',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'virt-who = virtwho.__main__:main',
            'virt-who-password = virtwho.password.__main__:main'
        ]
    },
    include_package_data=True,
    package_data={
        'virtwho.virt.esx': ['vimServiceMinimal.wsdl'],
    },
    cmdclass={
        'install_systemd': InstallSystemd,
        'install_upstart': InstallUpstart,
        'install_man_pages': InstallManPages,
        'install_config': InstallConfig,
        'build_py': rpm_version_release_build_py,
        'build': build
    },
    command_options={
        'egg_info': {
            'egg_base': ('setup.py', os.curdir),
        },
        'build_py': {
            'versioned_packages': ('setup.py', ['virtwho'])
        }
    }
)
