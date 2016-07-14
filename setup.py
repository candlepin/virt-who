#!/usr/bin/python2

import sys
import os
from setuptools import setup, find_packages
from distutils.command.install import install
from shutil import copy, copyfileobj
import gzip


def install_file(filename, destination, file_mode=0644, dir_mode=0755):
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
        install_file('virt-who-initscript', '{root}/etc/rc.d/init.d/virt-who'.format(root=root))


class InstallManPages(install):
    description = 'install manual pages'

    MAN_PAGES = (
        ('virt-who', '8'),
        ('virt-who-config', '5'),
        ('virt-who-password', '8'),
    )

    def run(self, *args, **kwargs):
        root = self.root or ''
        for name, number in self.MAN_PAGES:
            filename = '{name}.{number}'.format(name=name, number=number)
            dirname = '{root}/usr/share/man/man{number}'.format(root=root, number=number)
            if not os.path.isdir(dirname):
                os.makedirs(dirname, 0755)
            outfile = '{dirname}/{name}.{number}.gz'.format(
                dirname=dirname, name=name, number=number)

            with open(filename, 'rb') as f_in:
                with gzip.open(outfile, 'wb') as f_out:
                    copyfileobj(f_in, f_out)


class InstallConfig(install):
    description = 'install configuration filees'

    FILES = (
        ('virt-who.conf', '{root}/etc/sysconfig/virt-who'),
        ('template.conf', '{root}/etc/virt-who.d/template.conf'),
        ('template-general.conf', '{root}/etc/virt-who.conf'),
    )

    def run(self, *args, **kwargs):
        root = self.root or ''
        for origname, output in self.FILES:
            install_file(origname, output.format(root=root))


setup(
    name='virt-who',
    version='0.17',
    description='virt-who is agent for reporting virtual guest IDs to subscription manager.',
    # long_description=open('README.md').read(),
    author='Radek Novacek',
    author_email='rnovacek@redhat.com',
    license='LICENSE',
    url='https://fedorahosted.org/virt-who/',
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
    },
)
