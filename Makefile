
name = virt-who
version = 0.18

.PHONY: pack check install srpm rpm rpmlint upload

release:
	tito tag

pack:
	tito build --tgz -o .

check:
	pyflakes *.py

install:
	python setup.py install

srpm:
	tito build --srpm --test

rpm:
	tito build --rpm --test

rpmlint:
	$(eval tmpdir := $(shell mktemp -d))
	tito build --srpm --test -o $(tmpdir)
	tito build --rpm --test -o $(tmpdir)
	rpmlint $(name).spec $(tmpdir)/*
	rm -rf $(tmpdir)

upload: pack
	scp $(name)-$(version).tar.gz fedorahosted.org:$(name)

test:
	PYTHONPATH=. py.test

testmon:
	PYTHONPATH=. ptw -- --testmon --timeout 5

coverage:
	PYTHONPATH=. py.test -k 'not complex' --cov=. --cov-report=html --cov-report=term --cov-config .coveragerc

stylish:
	PYTHONPATH=. flake8
