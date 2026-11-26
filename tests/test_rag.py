import pytest

from kmd.site import rag


@pytest.mark.parametrize(("chapter", "node", "question", "excerpt"), [
    ("baraboshkin", "geo.baraboshkin.s1_2.02", "Что такое дельта", "#excerpt-u031_01-1"),
    ("baraboshkin", "geo.baraboshkin.s1_2.01", "Чем авандельта отличается от продельты?", "#excerpt-u030_04-1"),
    ("kuznetsov", "geo.kuznetsov.s10_1.02", "Чем биостром отличается от биогерма?", "#excerpt-u200_05-1"),
    ("latyshova", "geo.latyshova.s17.02", "Как образуется глинистая корка?", "#excerpt-u090_10-1"),
])
def test_retrieve_current_article(chapter, node, question, excerpt):
    _, passages = rag.retrieve(chapter, node, question)
    assert excerpt in {passage.href for passage in passages}
    _, unrelated = rag.retrieve(chapter, node, "Как выбрать материнскую плату для компьютера?")
    assert not unrelated


def test_follow_up_uses_recent_turns_and_local_sources(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")

    def complete(question, topic, passages, key, history):
        assert question == "А почему их делят на типы?"
        assert topic == "Три типа дельт"
        assert len(history) == 2
        assert "[S9]" not in history[-1]["answer"]
        index = next(i for i, p in enumerate(passages, 1) if "доминирующим процессом" in p.text)
        return f"Тип определяется доминирующим процессом. [S{index}]"

    monkeypatch.setattr(rag, "_complete", complete)
    result = rag.ask("baraboshkin", "geo.baraboshkin.s1_2.02", "А почему их делят на типы?", [
        {"question": "лишний вопрос", "answer": "старый ответ"},
        {"question": "Что такое дельта", "answer": "Ответ о дельтах"},
        {"question": "А подробнее?", "answer": "Ответ со ссылкой [S9]"},
    ])
    assert result["sources"][0]["href"] == "#excerpt-u031_01-1"
