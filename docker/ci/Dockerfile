FROM ubuntu:trusty
MAINTAINER Radek Novacek <rnovacek@redhat.com>
RUN apt-get update
RUN apt-get install -y python python-pip python-pytest python-dev git
RUN apt-get install -y libvirt0 swig libvirt-dev libssl-dev
RUN pip install -U iniparse python-dateutil M2Crypto libvirt-python unittest2 pytest-timeout mock
COPY . /virt-who
RUN pip install -r /virt-who/requirements.txt
WORKDIR /virt-who
CMD PYTHONPATH=. py.test --timeout=30
