from kmd.ingest.parse import build_units, cut_segment, detect_running_lines, split_pages, strip_description_blocks

MD = """<!-- page 1 -->
Old chapter text.
# Глава V
## § 17. ПЕРВЫЙ
Первый абзац заканчивается без точки и про-
<!-- page 2 -->
ГЛАВА V
должается здесь.

----
━━━ FORMAT 2: WELL LOG ━━━
Глубина 2190 м
KEYWORDS: каротаж

Рис. 5. Подпись рисунка
1 – глины; 2 – песок

Пример 3. Определить что-то. Ответ: 7.

# Задачи

86. Первая задача.
87. Вторая задача
<!-- page 3 -->
ГЛАВА V
продолжение второй.

Таблица 2.

| a | b |
| --- | --- |
| 1 | 2 |
# § 18. ВТОРОЙ
Текст.
<!-- page 4 -->
ГЛАВА V
## § 19. Конец
"""


def _units():
    md = MD.replace("\n", "\r\n").replace("\r\n", "\n")
    pages = split_pages(md)
    running = detect_running_lines(pages)
    seg = cut_segment(pages, 1, 3, "# Глава V", "## § 19.")
    return build_units(seg, running)


def test_cut_and_kinds():
    units, sections = _units()
    texts = [u["text"] for u in units]
    assert not any("Old chapter" in t for t in texts)
    assert not any("ГЛАВА V" == t for t in texts)  # running header removed
    para = next(u for u in units if u["text"].startswith("Первый абзац"))
    assert "продолжается здесь." in para["text"] and para["page_end"] == 2
    fig = next(u for u in units if u["kind"] == "figure")
    assert fig["figure_no"] == "5" and "Глубина 2190" in fig["description"] and "1 – глины" in fig["text"]
    assert any(u["kind"] == "example" for u in units)
    probs = [u for u in units if u["kind"] == "problem"]
    assert [p["problem_no"] for p in probs] == ["86", "87"]
    assert "продолжение второй" in probs[1]["text"]
    tab = next(u for u in units if u["kind"] == "table")
    assert tab["table_no"] == "2"
    assert [s["code"] for s in sections] == ["ch5", "s17", "s18"]


def test_strip_descriptions():
    t = "a\n----\n━━━ FORMAT 1 ━━━\nx 123\nKEYWORDS: k\nb"
    out = strip_description_blocks(t)
    assert "123" not in out and "a" in out and "b" in out
