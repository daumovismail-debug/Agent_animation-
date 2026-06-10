#!/bin/bash
# Полная установка PixarGen на VPS
# Запускай из папки /root/Agent_animation:
#   bash deploy/install.sh

set -e
PROJECT="/root/Agent_animation"

echo "=== 1. Устанавливаем Python зависимости ==="
pip install -q -r "$PROJECT/backend/requirements.txt"
pip install -q -r "$PROJECT/requirements.txt"

echo "=== 2. Собираем Next.js фронтенд ==="
cd "$PROJECT/frontend"
npm install --silent
npm run build

echo "=== 3. Копируем systemd сервисы ==="
cp "$PROJECT/deploy/pixargen-backend.service" /etc/systemd/system/
cp "$PROJECT/deploy/pixargen-frontend.service" /etc/systemd/system/

echo "=== 4. Копируем Nginx конфиг ==="
cp "$PROJECT/deploy/nginx.conf" /etc/nginx/sites-available/pixargen
ln -sf /etc/nginx/sites-available/pixargen /etc/nginx/sites-enabled/pixargen
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "=== 5. Запускаем сервисы ==="
systemctl daemon-reload
systemctl enable pixargen-backend pixargen-frontend
systemctl restart pixargen-backend pixargen-frontend

echo ""
echo "✅ PixarGen установлен!"
IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_IP")
echo "Сайт: http://$IP"
echo ""
echo "Управление:"
echo "  systemctl status pixargen-backend   # статус бэкенда"
echo "  systemctl status pixargen-frontend  # статус фронтенда"
echo "  journalctl -u pixargen-backend -f   # логи бэкенда"
echo "  journalctl -u pixargen-frontend -f  # логи фронтенда"
