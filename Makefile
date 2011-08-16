
name = virt-who
version = 0.1

.PHONY: pack check install srpm rpm
pack:
	git archive --format=tar --prefix=$(name)-$(version)/ master | gzip > $(name)-$(version).tar.gz

check:
	pyflakes *.py

install:
	install -d $(DESTDIR)/usr/share/$(name)/ $(DESTDIR)/usr/bin
	install -pm 0644 *.py $(DESTDIR)/usr/share/$(name)/
	install virt-who $(DESTDIR)/usr/bin/

srpm: pack
	rpmbuild --define "_sourcedir `pwd`" --define "_specdir `pwd`" --define "_srcrpmdir `pwd`" -bs $(name).spec

rpm: pack
	rpmbuild --define "_sourcedir `pwd`" --define "_specdir `pwd`" --define "_srcrpmdir `pwd`" --define "_rpmdir `pwd`" -bb $(name).spec

