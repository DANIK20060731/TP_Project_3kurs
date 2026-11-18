"""Нормализация текста рецензии и подсчёт значимых слов."""

from __future__ import annotations

import re
import unicodedata

# Краткий список служебных слов в нормализованном виде; он не подбирался под eval-набор.
STOP_WORDS = frozenset(
    {
        "а",
        "бы",
        "в",
        "во",
        "да",
        "для",
        "до",
        "же",
        "за",
        "и",
        "из",
        "или",
        "к",
        "ли",
        "на",
        "над",
        "не",
        "но",
        "о",
        "об",
        "от",
        "по",
        "под",
        "при",
        "про",
        "с",
        "со",
        "у",
        "что",
    }
)

_SEPARATORS = re.compile(r"[\W_]+")
_INVISIBLE_CATEGORIES = frozenset({"Cf", "Mn"})


def normalize(text: str) -> str:
    """Привести текст к нижнему регистру, заменить ё на е, пунктуацию на пробел.

    Цифры сохраняются, слова в результате разделены одним пробелом. Первая NFC собирает
    разложенные «й» и «ё» (буква плюс комбинируемый знак), чтобы удаление знаков их не изменило.
    Символы Cf и Mn (мягкий перенос, нулевая ширина, ударение) удаляются после нижнего регистра,
    потому что он сам может породить Mn. Вторая NFC собирает символы, которые стали соседними:
    без неё повторный вызов менял бы результат.
    """
    lowered = unicodedata.normalize("NFC", text).lower()
    visible = "".join(ch for ch in lowered if unicodedata.category(ch) not in _INVISIBLE_CATEGORIES)
    composed = unicodedata.normalize("NFC", visible).replace("ё", "е")
    return _SEPARATORS.sub(" ", composed).strip()


def significant_word_count(text: str) -> int:
    """Посчитать слова нормализованного текста без стоп-слов."""
    return sum(word not in STOP_WORDS for word in normalize(text).split())
