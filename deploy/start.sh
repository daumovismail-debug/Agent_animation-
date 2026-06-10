#!/bin/bash
# Запуск всего стека на VPS

set -e

PROJECT="/root/Agent_animation"

echo "=== Запуск бэкенда (FastAPI) ==="
cd "$PROJECT/backend"
nohup uvicorn main:app --host 127.0.0.1 --port 8000 --reload > /var/log/pixargen-backend.log 2>&1 &
echo "Бэкенд запущен (PID $!)"

echo "=== Запуск фронтенда (Next.js) ==="
cd "$PROJECT/frontend"
nohup npm run start > /var/log/pixargen-frontend.log 2>&1 &
echo "Фронтенд запущен (PID $!)"

echo "=== Копируем Nginx конфиг ==="
cp "$PROJECT/deploy/nginx.conf" /etc/nginx/sites-available/pixargen
ln -sf /etc/nginx/sites-available/pixargen /etc/nginx/sites-enabled/pixargen
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "✅ Всё запущено!"
echo "Сайт доступен на http://$(curl -s ifconfig.me)"
echo ""
echo "Логи:"
echo "  tail -f /var/log/pixargen-backend.log"
echo "  tail -f /var/log/pixargen-frontend.log"
