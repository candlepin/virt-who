echo "GIT_COMMIT:" "${GIT_COMMIT}"

cd $WORKSPACE

virtualenv env-stylish -p python3
source env-stylish/bin/activate

pip install -r requirements.txt
pip install -U flake8

export PYTHONPATH=.
make stylish
