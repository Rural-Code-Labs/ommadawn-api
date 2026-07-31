#!/bin/bash
set -e

HOST="vattenbit@192.168.1.54"
APP_DIR="/home/vattenbit/ommadawn-api"

echo "→ Desplegando en preproducción ($HOST)..."

ssh "$HOST" "
  set -e
  cd $APP_DIR

  echo '→ Actualizando código...'
  git pull

  echo '→ Instalando dependencias...'
  .venv/bin/pip install -e '.[dev]' -q

  echo '→ Aplicando migraciones...'
  .venv/bin/alembic upgrade head

  echo '→ Reiniciando servicio...'
  sudo systemctl restart ommadawn-api

  echo '→ Estado del servicio:'
  systemctl is-active ommadawn-api
"

echo "✓ Despliegue completado"
