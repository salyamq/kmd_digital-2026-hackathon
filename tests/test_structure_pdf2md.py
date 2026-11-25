from kmd.ingest.parse import _find_marker
from kmd.ingest.pdf2md import _join_lines, _join_spaced, quality


def test_letter_spaced_words_are_joined():
    assert _join_spaced("П л о с к о п а р а л л е л ь н о е") == "Плоскопараллельное"
    assert _join_spaced("в  о д н о м е р н о е  движение") == "в одномерное движение"


def test_hyphenation_and_soft_hyphens():
    assert _join_lines(["коэффициентом пьезопро-", "водности пласта"]) == "коэффициентом пьезопроводности пласта"
    assert _join_lines(["друго\u00ad", "го вида"]) == "другого вида"
    assert _join_lines(["Северо-", "Западный"]) == "Северо- Западный"


def test_quality_flags_garbage():
    good = "Давление в пласте перераспределяется длительно после пуска скважины. " * 5
    assert quality(good)["good"]
    bad = "dpldt = %д2р1дх2 ^ {х} \\ ро Р{х,0} " * 10
    assert not quality(bad)["good"]


def test_fuzzy_heading_marker():
    pages = {30: "текст\n1.2 Дельты [Deltas]\nДельты — это", 31: "дальше"}
    assert _find_marker(pages, [30, 31], "## 1.2 Дельты") == (30, 1)
    pages = {5: "ГЛАВА XXIII\nНЕУСТАНОВИВШЕЕСЯ ДВИЖЕНИЕ УПРУГОИ\nЖИДКОСТИ"}
    assert _find_marker(pages, [5], "# Глава XXIII Неустановившееся движение упругой жидкости") == (5, 0)
