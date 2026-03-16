FROM python:3.12-slim

WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du projet
COPY . .

# Collecte des fichiers statiques
RUN python manage.py collectstatic --noinput

EXPOSE 8080

CMD ["gunicorn", "cntso.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "2"]
