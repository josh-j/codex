#!/bin/bash
rm -rf .venv-vcsa
python3.12 -m venv .venv-vcsa
.venv-vcsa/bin/pip install --upgrade pip
.venv-vcsa/bin/pip install 'ansible-core>=2.15,<2.16' pyvmomi pykerberos
.venv-vcsa/bin/ansible-galaxy collection install -r requirements.yml
