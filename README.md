# virt-who

virt-who is agent for reporting virtual guest IDs to subscription manager.

It works either locally or via remote hypervisor. It obtains association between hosts and guests in the given
environment (e.g. hypervisor or local system) and then reports it to the subscription manager platform.


## Installation

To just install it use:

```
# make DESTDIR=/usr install
```

You can also create rpm package with:

```
$ make rpm
```

and then install the package


## Supported hypervisors

virt-who can obtain list of guest running on given machine or association between hosts and guests in given
virtualization environment.

Backends for reporting list of guest running on given machine:

* libvirt

Backends for reporting hosts to guests association:

* VMWare vCenter Server and ESX(i)
* Hyper-V
* Remote libvirt
* Kubevirt
* Nutanix AHV Virtualization


## Supported subscription managers

virt-who can report the guest lists and host/guest associations to following subscription management systems:

* Red Hat Subscription Management (RHSM)
* Satellite 6


## Configuration


See the [virt-who-config(5)](virt-who-config.5) manual page.

## Usage

See the [virt-who(8)](virt-who.8) manual page.
