FROM ubuntu:trusty
MAINTAINER Radek Novacek <rnovacek@redhat.com>
RUN apt-get update && \
    apt-get upgrade -y python-requests && \
    apt-get install -y python python-pip python-pytest python-dev git libvirt0 swig libvirt-dev libssl-dev && \
    pip install -U iniparse python-dateutil M2Crypto libvirt-python unittest2 pytest-timeout mock
COPY . /virt-who
RUN pip install -r /virt-who/requirements.txt
WORKDIR /virt-who
CMD PYTHONPATH=. py.test --timeout=30
