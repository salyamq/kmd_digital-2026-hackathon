# HANDOFF — что не сделано (состояние на 2026-11-25, вечер)

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

Ключа API нет. `kmd/llm.py`: провайдер `queue` пишет запросы в `runs/<ch>/llm/pending/*.json`, этап
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
- Курсы + сайты: `runs/latyshova/site`, `runs/kuznetsov/site`.
- Ролики: `runs/latyshova/video/geo.latyshova.s20.01/short.mp4`, `runs/basniev/video/geo.basniev.s5_2.13/long.mp4` (+ паспорта).
- Перерисовка рисунков книги кодом (latyshova 9 рис., basniev 24.3, kuznetsov 10.2).
- PDF-only ingest (`kmd/ingest/pdf2md.py`), модуль проверки (`kmd check`), `kmd domain`, метрики (`python -m kmd.metrics`).

## НЕ сделано — по приоритету

1. **`make run` не доходит до конца на latyshova** (блокер допуска «жюри запускает по инструкции»):
   этап `scenes` создаёт 16 запросов сцен для узлов с форматом interactive/short/long, у которых нет
   спецификации (в кэше есть только сцены двух роликов) → выход с кодом 3. Нужно: либо ответить на эти
   запросы (тогда в курсе появятся интерактивы/анимации — см. п. 3), либо сделать так, чтобы `scenes`
   по умолчанию не блокировал `course/site` (флаг/только узлы с роликом). Проверить с чистого клона:
   `make run CH=latyshova && make run CH=kuznetsov` → код 0, 0 pending.
2. **Курс Басниева**: 31 из 60 ответов `course_step` в кэше; осталось 29 (`kmd course basniev` → ответить →
   повторять до 0 pending и 0 ошибок проверки → `kmd site basniev` → проверить в браузере на 390/1280 px).
   В рабочей копии есть незакоммиченные частичные `runs/basniev/{tasks.json,cards.json,illustrations/}` —
   их перезапишет этап.
3. **Видеоузлы без ролика не закрыты интерактивом/анимацией** (ТЗ: «в главе без ролика видеоузлы закрывают
   интерактив или анимация»). У kuznetsov 7 short + 2 long + 6 interactive узлов, сцен нет вообще; у latyshova
   и basniev — только по одной сцене. Нужны спецификации сцен (`kmd scenes CH`) → курс покажет кадры/слайдер.
4. **Страница «Перед главой»** в курсе: детерминированно из `kmd.ingest.analysis_context(ch)` (предпосылки,
   зависимости глав, ключевые определения) с пометкой «из анализа книги (машинный), не текст автора».
5. **Репетиция на незнакомой главе** до заморозки: взять главу другой книги (лучше английскую, и один PDF-скан
   без md) → `chapters/<id>.yaml` → `make run`. Не проверено: OCR сканов через vision-LLM (только tesseract),
   английский язык на всех этапах, глава из бурения (`kmd domain drilling --from-chapter <id>`).
6. **Журнал ручных правок пуст** (`edits/journal.jsonl` не существует). Все правки — через
   `overrides/<ch>/<node>.json` + `python -m kmd edit ... --minutes N`; затем `make rebuild CH=...`.
   Проверить, что `make rebuild` реально пересобирает шаг и сайт после override (end-to-end не проверено).
7. **Заморозка**: `make test` (сейчас 53 теста зелёные), `uv pip freeze -p .venv > requirements.lock`,
   README/MANIFEST проверить по факту, `git tag freeze-<дата>` и push. После тега код, `prompts/`, `domains/` не трогать.
8. **Метрики**: прогнать `python -m kmd.metrics` → `runs/metrics.json`; цены за токен в `kmd/metrics.py`
   (env `KMD_PRICE_IN/OUT`) — подставить реальные для выбранной модели.
9. **Модуль проверки на наборе закладок организаторов** не прогонялся (набора нет в наших материалах; проверить
   Drive). Калибровка была только на наших синтетических пакетах (см. `docs/notes/structure.md`).
10. Мелочи: удалить тестовые папки `runs/fixture_latyshova`, `runs/stub_visuals`, `domains/demo_hydro`
    (или держать вне основного списка); у перерисовок нет варианта для телефона (мелкий текст на 390 px);
    в `domains/geology/difficulty_types.yaml` имена шаблонов разрешаются через алиасы в
    `kmd/visuals/illustrate.py` — заменить на канонические, шаблона `pore_scale` нет;
    edge-tts из песочницы ограничивает частоту (запасной голос piper включается на весь ролик);
    кэширование промптов у провайдера не реализовано (снизило бы цену входа).
11. Курсы по контрольным главам сознательно не делались (организаторы контроль не оценивают).

## Правила

- Ничего под конкретную главу в коде; предметное — только в `domains/`.
- Сгенерированные файлы руками не правим — только overrides + журнал.
- Не запускать двух работников на одну главу одновременно.
- Коммитить свои пути (`git add <paths>`), не `git add -A`; большие бинарники не коммитить, кроме финальных mp4 < 25 МБ.
