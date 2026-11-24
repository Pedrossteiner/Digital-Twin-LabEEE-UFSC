#!/bin/sh
# Pacotes mensais em segundo plano + página web.
python mensal.py &
exec gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 2 --timeout 600 --access-logfile - web:app
