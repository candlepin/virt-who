echo "GIT_COMMIT:" "${GIT_COMMIT}"

cd $WORKSPACE

sudo dnf update -y
sudo dnf install -y libnl3-devel swig python3-libvirt
sudo yum-builddep -y virt-who.spec 

virtualenv env-pytest -p python3
source env-pytest/bin/activate

pip install -U setuptools
pip install -r requirements.txt
pip install -r requirements-test.txt
pip install -U python-dateutil M2Crypto libvirt-python unittest2 

export PYTHONPATH=.
py.test --timeout=30 -v
