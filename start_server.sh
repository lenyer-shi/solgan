#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "========================================="
echo "  EEM Fingerprint Web Service"
echo "========================================="
echo "  Frontend:  http://localhost:8000/"
echo "  API Docs:  http://localhost:8000/docs"
echo "========================================="
python3 server.py
