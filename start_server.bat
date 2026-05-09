@echo off
chcp 65001 >nul
cd /d %~dp0
echo =========================================
echo   EEM Fingerprint Web Service
echo =========================================
echo  Frontend:  http://localhost:8000/
echo  API Docs:  http://localhost:8000/docs
echo =========================================
python server.py
pause
