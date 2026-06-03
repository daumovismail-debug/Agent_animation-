#!/usr/bin/env bash
# Установка бота как systemd-сервиса.
# Использование на сервере:
#   cd /root/Agent_animation-
#   sudo bash deploy/install-systemd.sh

set -e

PROJECT_DIR="/root/Agent_animation-"
ENV_FILE="/etc/agent-bot.env"
UNIT_FILE="/etc/systemd/system/agent-bot.service"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Проект не найден в $PROJECT_DIR — поправь PROJECT_DIR в скрипте." >&2
  exit 1
fi

# 1. Env-файл с токеном (создаём только если ещё не существует, не перезатираем)
if [ ! -f "$ENV_FILE" ]; then
  echo "Создаю $ENV_FILE — впиши туда TELEGRAM_BOT_TOKEN."
  cat > "$ENV_FILE" <<'EOF'
# Telegram-бот: токен от @BotFather
TELEGRAM_BOT_TOKEN=

# Опциональный fallback на API-ключ (если Claude Agent SDK не подцепит подписку)
# ANTHROPIC_API_KEY=
EOF
  chmod 600 "$ENV_FILE"
  echo "→ Открой $ENV_FILE редактором и впиши токен, затем перезапусти этот скрипт."
  exit 0
fi

# Проверим, что токен реально вписан
if ! grep -qE '^TELEGRAM_BOT_TOKEN=.+' "$ENV_FILE"; then
  echo "В $ENV_FILE пустой TELEGRAM_BOT_TOKEN — впиши и перезапусти." >&2
  exit 1
fi

chmod 600 "$ENV_FILE"

# 2. Копируем unit-файл
cp "$PROJECT_DIR/deploy/agent-bot.service" "$UNIT_FILE"
chmod 644 "$UNIT_FILE"

# 3. Активируем и запускаем
systemctl daemon-reload
systemctl enable agent-bot.service
systemctl restart agent-bot.service

echo
echo "Готово. Полезные команды:"
echo "  systemctl status agent-bot          # текущее состояние"
echo "  journalctl -u agent-bot -f          # логи в реальном времени"
echo "  systemctl restart agent-bot         # перезапуск (после git pull)"
echo "  systemctl stop agent-bot            # остановить"
echo "  systemctl disable agent-bot         # убрать из автозапуска"
