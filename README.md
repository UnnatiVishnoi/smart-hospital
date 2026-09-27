# MediServe - Smart Hospital Management System

A Django-based hospital equipment maintenance, inventory, and knowledge management system.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your DJANGO_SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Production Deployment

See [DEPLOY.md](DEPLOY.md).
