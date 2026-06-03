# Agent Animation — генератор промтов для ИИ-видео (Grok)

MVP-агент, который превращает идею в готовый набор промтов для видео-генератора **Grok (xAI)**.

## Что делает

1. Берёт идею: `python agent.py "кот-астронавт спасает планету"`
2. Через Claude API разбивает её на сцены (сценарий)
3. Для каждой сцены генерирует оптимизированный промт под Grok video
4. Сохраняет результат в `output/<название>.md` и `output/<название>.json`

Готовые промты можно скопировать в Grok и получить видео.

## Установка

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Использование

```bash
# Минимально
python agent.py "девочка идёт по неоновому Токио под дождём"

# С параметрами
python agent.py "космический корабль входит в червоточину" \
    --style cinematic \
    --scenes 5 \
    --duration 6 \
    --aspect 16:9
```

### Параметры

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `--style` | cinematic / anime / 3d / realistic / cartoon | cinematic |
| `--scenes` | сколько сцен в видео | 4 |
| `--duration` | длительность одной сцены (сек) | 6 |
| `--aspect` | соотношение сторон | 16:9 |
| `--out` | папка для результатов | `output/` |

## Структура

```
agent/
  __init__.py
  script.py           # идея -> сценарий (Claude API)
  prompt_builder.py   # сцена -> промт под Grok
  models.py           # датаклассы Scene, VideoProject
  cli.py              # точка входа
prompts/
  system_script.md    # системный промт для сценариста
  system_prompter.md  # системный промт для промт-инженера Grok
  styles.json         # пресеты стилей
output/               # сюда падают результаты
```

## Дальше (не MVP)

- Вызов Grok video API когда выйдет публичный доступ
- Озвучка через ElevenLabs
- Музыка через Suno
- Автоматический монтаж через ffmpeg
