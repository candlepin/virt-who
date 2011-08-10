
name = libvirt-rhsm
version = 0.1

pack:
	git archive --format=tar --prefix=$(name)-$(version)/ master | gzip > $(name)-$(version).tar.gz

check:
	pyflakes *.py

install:
	install -d $(DESTDIR)/usr/share/libvirt-rhsm/ $(DESTDIR)/usr/bin
	install -pm 0644 *.py $(DESTDIR)/usr/share/libvirt-rhsm/
	install libvirt-rhsm $(DESTDIR)/usr/bin/

