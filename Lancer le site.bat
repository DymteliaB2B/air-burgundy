@echo off
title AIR BURGUNDY - Site et API
cd /d "%~dp0"
start "" http://127.0.0.1:8080
python server.py
pause
