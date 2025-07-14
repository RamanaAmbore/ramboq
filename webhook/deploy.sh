#!/bin/bash

cd /opt/ramboq
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
systemctl restart ramboq
