import pytest

from outage_bot.core.normalize import house_key, search_token, street_aliases, street_key


@pytest.mark.parametrize(
    "a,b",
    [
        ("просп. Яворницького Дмитра", "вул. Дмитра Яворницького"),
        ("пр-т. Олександра Поля", "просп. Поля Олександра"),
        ("ПРОСП. ОЛЕКСАНДРА ПОЛЯ", "олександра поля"),
        ("вул. Воз`єднання України", "вул. Воз’єднання України"),
        ("пров. Тупиковий", "Тупиковий"),
        ("ул. Робоча", "вулиця Робоча"),
    ],
)
def test_street_key_equal(a, b):
    assert street_key(a) == street_key(b)


def test_street_key_keeps_name_words():
    assert street_key("вул. Січеславська Набережна") != street_key("вул. Січеславська")
    assert street_key("Запорізьке шосе") != street_key("вул. Запорізька")


def test_aliases_include_old_name():
    assert street_aliases("вул. Автоклубна (Виборзька)") == ["автоклубна", "виборзька"]


def test_search_token_is_longest_word():
    assert search_token("просп. Дмитра Яворницького") == "яворницького"


@pytest.mark.parametrize(
    "raw,key",
    [("58/А", "58А"), ("58 а", "58А"), ("58a", "58А"), ("8//1", "8/1"), ("16/2", "16/2"), ("б/н", "Б/Н")],
)
def test_house_key(raw, key):
    assert house_key(raw) == key
