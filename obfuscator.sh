#!/bin/bash
pip install pyarmor
pyarmor gen -O dist main.py api/ core/ database/ handlers/ utils/
rm -rf api core database handlers utils main.py
mv dist/* .
rm -rf dist
