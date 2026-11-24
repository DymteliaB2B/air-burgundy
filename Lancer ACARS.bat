@echo off
chcp 65001 >nul
title AIR BURGUNDY - ACARS
cd /d "%~dp0"
python acars.py %*
pause
