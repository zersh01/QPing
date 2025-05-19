#!/bin/bash
# run background without terminal output
nohup python3 qping.py >/dev/null 2>&1 &
