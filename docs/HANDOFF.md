# HANDOFF · 25 ноября 2026

Прочитать сначала: `README.md`, `docs/ARCHITECTURE.md` (контракт этапов), `docs/TZ.md` (задание, таблица
оценки в конце), `docs/PLAYBOOK.md`, заметки владельцев `docs/notes/{structure,course,visuals}.md`.

## Окружение

```bash
git clone https://github.com/salyamq/kmd_digital-2026-hackathon && cd kmd_digital-2026-hackathon
make setup                                   # uv + Python 3.12; apt: ffmpeg espeak-ng tesseract-ocr tesseract-ocr-rus
```
Книги не в git. Скачать из Google Drive (папка организаторов) в `~/kmd_data` (или `KMD_DATA=...`) с такими именами:

| файл | откуда (Drive) |
|---|---|
| `md/train_latyshova.md`, `md/train_basniev.md`, `md/train_kuznetsov.md`, `md/ctrl_vendelshtein.md`, `md/ctrl_barenblatt.md`, `md/ctrl_baraboshkin_b.md` | папка `books md` (имена те же) |
| `pdf/latyshova.pdf`, `pdf/basniev.pdf`, `pdf/kuznetsov.pdf`, `pdf/vendelshtein.pdf`, `pdf/barenblatt.pdf`, `pdf/baraboshkin.pdf` | папка `книги` (переименовать по автору) |
| `analyses/<id>.md` (6 шт., id как в `chapters/`) | папка с анализами книг (JSON-анализы, сгенерированы моделью организаторов) |

PDF > 10 МБ не качаются через Drive MCP — качать прямой ссылкой
`https://drive.usercontent.google.com/download?id=<ID>&export=download&confirm=t`.

## Как работает LLM (важно)

С ключом и моделью из локального `.env` конвейер вызывает API. Без ключа провайдер `queue` пишет запросы в `runs/<ch>/llm/pending/*.json`, этап
печатает их и выходит с кодом 3. Работник (агент) отвечает:
```bash
.venv/bin/python -m kmd llm pending
.venv/bin/python -m kmd llm show <pending.json>        # system + user (+ пути картинок, если есть — открыть их)
.venv/bin/python -m kmd llm answer <pending.json> <answer.json>   # валидирует JSON-схемой, кладёт в кэш
```
Правило: отвечать **только по содержимому запроса**, как API-модель; если в запросе чего-то не хватает —
чинить промпт/код, а не ответ. Ответы закэшированы и коммитятся (`runs/<ch>/llm/<task>/<key>.json`),
`pending/` в .gitignore. С ключом (`ANTHROPIC_API_KEY` или `OPENAI_API_KEY`+`OPENAI_BASE_URL`, `KMD_LLM_MODEL`
в `.env`) всё идёт автоматически.

Осторожно: изменение текста промпта, схемы или каталога шаблонов (`kmd.visuals.catalog_text()`, он вшит в
промпт `course_step`) меняет ключи кэша → все шаги будут запрошены заново (дорого). Если правка
только косметическая, есть `python -m kmd.course.reuse CH` (переподаёт старые ответы с полной перепроверкой)
и `python -m kmd.layer.migrate CH`.

## Готово

- Слои (layer/verify/route), 0 ошибок проверки: все 6 глав.
- Офлайн-библиотека `runs/index.html` ведёт в учебные курсы Латышовой, Басниева и Кузнецова и в репетицию.
- Обязательные ролики 9:16 и 16:9 встроены в курсы Латышовой и Басниева. У Кузнецова добавлены
  два шортса с паспортами для `geo.kuznetsov.s10_2.10` и `geo.kuznetsov.s10_3.05`.
- Приём Markdown и отдельных изображений страниц реализован через `book.md` и `book.page_images`.
  Поддерживается автоматическое извлечение текста и сканов из PDF. Оба режима проверены с API.
- Проверка закладок читает пакет организаторов с изображениями и выдаёт поле `remarks` по их схеме.
- Отчёт о видеоёмких узлах сохраняется в `runs/<id>/template_coverage.json` при сборке сайта.
- `kmd export <id>` собирает JSON для сдачи в `runs/<id>/submission/` и проверяет его по схемам
  организаторов. Команда также работает на сокращённом прогоне после маршрутизации.
- Перерисовка рисунков книги кодом (latyshova 9 рис., basniev 24.3, kuznetsov 10.2).
- PDF-only ingest (`kmd/ingest/pdf2md.py`), модуль проверки (`kmd check`), `kmd domain`, метрики (`python -m kmd.metrics`).

## Проверка перед сдачей

- [Репетиция и замеры](notes/rehearsal.md) содержат итоги запуска без API на Латышовой, прогонов
  Баренблатта через OpenRouter и калибровки проверяющего модуля.
- Для новых учебников проверьте таблицу покрытия, `verify_report.json`, список исключённых заданий
  в `course_report.json` и отчёт `template_coverage.json`. Если сцена не проходит проверки, шаг
  показывает разбор по цитатам. На шагах без медиа остаются иллюстрации курса.
- Слепая проверка пакета дала 13 полных и 5 частичных находок. После улучшения привязки к страницам
  и проверки замечаний — 15 полных находок из 21 и четыре ложные тревоги при ориентире ТЗ в две.
- Для ручной правки запишите патч в `overrides/<ch>/<node>.json` и вызовите `kmd edit` с минутами.
  `make rebuild CH=<id> VIDEO=1` одновременно пересобирает курс и имеющиеся ролики.
- Официальные три двойника и глава по бурению выдаются после заморозки. Перед выдачей, по команде
  координатора, выполнить `make test`, сохранить `uv pip freeze -p .venv > requirements.lock`,
  обновить этот документ, сделать коммит, поставить тег `freeze-<дата>` и отправить `main` и тег.
  После тега использовать YAML глав и журналируемые overrides. Детали в [плейбуке](PLAYBOOK.md).

## Правила

- Ничего под конкретную главу в коде; предметное — только в `domains/`.
- Сгенерированные файлы руками не правим — только overrides + журнал.
- Не запускать двух работников на одну главу одновременно.
- Коммитить свои пути (`git add <paths>`), не `git add -A`; большие бинарники не коммитить, кроме финальных mp4 < 25 МБ.
