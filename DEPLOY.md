# MediServe Deployment Guide

## Prerequisites

- Ubuntu 22.04+ server
- Python 3.10+
- MySQL 8.0+ (or use SQLite for small deployments)
- nginx
- systemd

## 1. Server Setup

```bash
# Install system packages
sudo apt update
sudo apt install python3-venv python3-pip nginx mysql-server

# Create app directory
sudo mkdir -p /opt/mediserver
sudo chown $USER:$USER /opt/mediserve
```

## 2. Deploy Code

```bash
cd /opt/mediserver
git clone <your-repo-url> .
```

## 3. Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Environment Variables

Create `.env`:

```
DJANGO_SECRET_KEY=<generate-with: python -c "import secrets; print(secrets.token_urlsafe(64))">
DJANGO_SETTINGS_MODULE=config.settings_production
DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DJANGO_CSRF_TRUSTED=https://yourdomain.com,https://www.yourdomain.com

# Database (MySQL production)
DB_ENGINE=mysql
DB_NAME=shms_db
DB_USER=shms_user
DB_PASSWORD=<strong-password>
DB_HOST=127.0.0.1
DB_PORT=3306

# Optional: LLM chatbot
LLM_API_KEY=
LLM_MODEL=
LLM_BASE_URL=
```

## 5. Database

```bash
# If using MySQL:
sudo mysql -e "CREATE DATABASE shms_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER 'shms_user'@'127.0.0.1' IDENTIFIED BY '<password>';"
sudo mysql -e "GRANT ALL PRIVILEGES ON shms_db.* TO 'shms_user'@'127.0.0.1';"
sudo mysql -e "FLUSH PRIVILEGES;"

python manage.py migrate
python manage.py createsuperuser
```

## 6. Static Files

```bash
python manage.py collectstatic --noinput
```

## 7. nginx Configuration

Copy the included nginx config:

```bash
sudo cp deploy/nginx_mediserver.conf /etc/nginx/sites-available/mediserver
# Edit server_name in the config
sudo ln -sf /etc/nginx/sites-available/mediserver /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 8. Systemd Service

```bash
sudo cp deploy/mediserver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mediserver
```

## 9. SSL with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```
