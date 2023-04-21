#!/bin/bash

dnf install -y libnl3-devel python3-libvirt python3-dateutil python3-setuptools python3-pip dnf-plugins-core \
    python3-requests python3-cryptography python3-subscription-manager-rhsm subscription-manager
dnf builddep -y virt-who.spec

pip install -r requirements.txt
pip install -r requirements-test.txt
