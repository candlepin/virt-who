#!/usr/bin/python2
# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
from bs4 import BeautifulSoup


class InvalidXmlError(Exception):
    pass


already_included = set()


def process_file(filename):
    xml = BeautifulSoup(open(filename), "xml")
    for include in xml.find_all(['include', 'import']):
        location = None
        for attr, value in include.attrs.items():
            if attr.lower() == 'schemalocation':
                location = value
            if attr.lower() == 'location':
                location = value
        if not location:
            raise InvalidXmlError("No schemalocation attribute: %s" % (include.prettify()))
        if location in already_included:
            include.decompose()
            continue
        else:
            already_included.add(location)
        filename = os.path.join(os.path.dirname(vimfile), location)
        inc_xml = process_file(filename)
        for tag in inc_xml.find_all(True, recursive=False):
            if include.parent.name == tag.name:
                for subtag in tag.find_all(True, recursive=False):
                    include.insert_before(subtag)
            else:
                include.insert_before(tag)
        include.decompose()
    return xml


def clean_up_vim(vim, keep_methods=None, keep_types=None):
    if keep_types is None:
        keep_types = set()
    keep_messages = set()
    for operation in vim.binding.find_all('operation', recursive=False):
        if operation['name'] in keep_methods:
            pass
        else:
            operation.decompose()

    for operation in vim.portType.find_all('operation', recursive=False):
        if operation['name'] in keep_methods:
            for io in operation.find_all(['input', 'output'], recursive=False):
                keep_messages.add(io['message'].rpartition(":")[2])
            for fault in operation.find_all('fault', recursive=False):
                keep_messages.add(fault['message'].rpartition(":")[2])
                keep_types.add(fault['name'])
        else:
            operation.decompose()

    print("Keep messages:", keep_messages, file=sys.stderr)
    for message in vim.definitions.find_all('message', recursive=False):
        if message['name'] in keep_messages:
            for part in message.find_all('part', recursive=False):
                keep_types.add(part['element'].rpartition(":")[2])
        else:
            message.decompose()

    # Gather recursive types
    changed = True
    while changed:
        changed = False
        for type in vim.types.schema.find_all(True, recursive=False):
            if 'name' in type.attrs and type['name'] in keep_types:
                if 'type' in type.attrs:
                    t = type.attrs['type'].rpartition(":")[2]
                    if t not in keep_types:
                        changed = True
                    keep_types.add(t)
                for ext in type.find_all('extension'):
                    t = ext['base'].rpartition(":")[2]
                    if t not in keep_types:
                        changed = True
                    keep_types.add(t)
                for element in type.find_all('element'):
                    t = element['type'].rpartition(":")[2]
                    if t not in keep_types:
                        changed = True
                    keep_types.add(t)

    print("Keep types:", keep_types, file=sys.stderr)
    for type in vim.types.schema.find_all(True, recursive=False):
        if 'name' not in type.attrs or type['name'] not in keep_types:
            type.decompose()

    return vim

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: %s /path/to/vim.wsdl")
        sys.exit(1)

    vimfile = sys.argv[1]

    # replace the includes
    vim = process_file(vimfile)
    vim.definitions.attrs['xmlns:vim25'] = "urn:vim25"
    vim.definitions.attrs['targetNamespace'] = "urn:vim25"
    vim.definitions.attrs['xmlns:mime'] = "http://schemas.xmlsoap.org/wsdl/mime/"
    vim.definitions.attrs['xmlns:xsd'] = "http://www.w3.org/2001/XMLSchema"
    with open('/tmp/vim_full.xml', 'w') as f:
        f.write(vim.prettify())
    filtered_vim = clean_up_vim(
        vim,
        keep_methods=set((
            'Login', 'RetrieveServiceContent', 'RetrieveProperties',
            'RetrievePropertiesEx', 'CreateFilter', 'WaitForUpdatesEx',
            'DestroyPropertyFilter', 'CancelWaitForUpdates')),
        keep_types=set((
            'TraversalSpec', 'ArrayOfManagedObjectReference',
            'ArrayOfDynamicProperty', 'DynamicData', 'VimFault',
            'PropertyFilterSpec')))
    '''ManagedObjectReference', 'ServiceContent',
    'AboutInfo', 'UserSession', 'ObjectSpec',
    'DynamicProperty', 'TraversalSpec',
    'PropertyFilterSpec', 'PropertySpec'''
    print(filtered_vim.prettify())
