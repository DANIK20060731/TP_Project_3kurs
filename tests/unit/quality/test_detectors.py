"""Спецификация ядра детекторов халтурных рецензий (T-011, FR-6.1)."""

from __future__ import annotations

import ast
import dataclasses
import itertools
import json
import os
import random
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from apps.quality.detectors import (
    CopyPaste,
    Detector,
    Flag,
    QualityConfig,
    ReviewText,
    TooFast,
    TooShort,
    UniformScores,
    normalize,
    run_all,
)

ROOT = Path(__file__).resolve().parents[3]

DETECTOR_NAMES = {"too_short", "copy_paste", "uniform_scores", "too_fast"}

# Заведомо значимые слова: существительные, которых нет ни в одном разумном списке стоп-слов.
NOUNS = [
    "алгоритм",
    "структура",
    "таблица",
    "запрос",
    "сервер",
    "клиент",
    "модуль",
    "функция",
    "переменная",
    "интерфейс",
    "компилятор",
    "сокет",
    "протокол",
    "маршрутизатор",
    "архитектура",
    "документация",
    "диаграмма",
    "рисунок",
    "формула",
    "измерение",
    "погрешность",
    "эксперимент",
    "гипотеза",
    "источник",
    "библиотека",
    "репозиторий",
    "ветка",
    "коммит",
    "транзакция",
    "индекс",
    "кэш",
    "очередь",
    "поток",
    "процессор",
    "память",
    "диск",
    "файл",
    "каталог",
    "драйвер",
    "контейнер",
    "образ",
    "сеть",
    "подсеть",
]
STOP_WORDS = ("и", "в", "на", "не", "что")


def words(count: int, start: int = 0) -> str:
    """Строка из count разных значимых слов."""
    assert start + count <= len(NOUNS)
    return " ".join(NOUNS[start : start + count])


def make_review(
    review_id: str = "rev-1",
    comment: str = "",
    *,
    reviewer_id: str = "petrov7",
    scores: tuple[int, ...] = (5, 4, 3),
    seconds_spent: int | None = 600,
) -> ReviewText:
    return ReviewText(
        review_id=review_id,
        reviewer_id=reviewer_id,
        comment=comment,
        scores=scores,
        seconds_spent=seconds_spent,
    )


def flags_by_id(flags: list[Flag]) -> dict[str, Flag]:
    """Индекс флагов по рецензии; заодно проверяет, что на рецензию не больше одного флага."""
    ids = [flag.review_id for flag in flags]
    assert len(ids) == len(set(ids)), f"На рецензию больше одного флага: {flags}"
    return {flag.review_id: flag for flag in flags}


def canonical(flags: list[Flag]) -> list[Flag]:
    return sorted(flags, key=lambda f: (f.review_id, f.detector, f.reason, f.score))


# Пороги вне 0 < T <= 1, включая значения, на которых наивные сравнения пропускают nan.
INVALID_THRESHOLDS = [0, -0.1, 1.0000001, float("nan"), float("inf")]


# ---------------------------------------------------------------- контракт типов


class TestContract:
    def test_review_text_is_frozen_dataclass_with_contract_fields(self) -> None:
        """AC-6, контракт CLAUDE.md: ReviewText — frozen dataclass с полями контракта."""
        review = make_review()
        assert [f.name for f in dataclasses.fields(ReviewText)] == [
            "review_id",
            "reviewer_id",
            "comment",
            "scores",
            "seconds_spent",
        ]
        with pytest.raises(dataclasses.FrozenInstanceError):
            review.comment = "другой"  # type: ignore[misc]

    def test_flag_is_frozen_dataclass_without_reviewer_field(self) -> None:
        """AC-6, инвариант анонимности: во Flag нет поля с автором рецензии."""
        flag = Flag(review_id="rev-1", detector="too_short", reason="коротко", score=0.5)
        assert [f.name for f in dataclasses.fields(Flag)] == [
            "review_id",
            "detector",
            "reason",
            "score",
        ]
        with pytest.raises(dataclasses.FrozenInstanceError):
            flag.score = 1.0  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("detector", "name"),
        [
            (TooShort(min_words=30), "too_short"),
            (CopyPaste(threshold=0.8), "copy_paste"),
            (UniformScores(), "uniform_scores"),
            (TooFast(min_seconds=60), "too_fast"),
        ],
    )
    def test_detector_exposes_name_and_empty_input_gives_no_flags(
        self, detector: Detector, name: str
    ) -> None:
        """AC-2..AC-5: имя в атрибуте name; пустой вход не даёт флагов."""
        assert detector.name == name
        assert detector.detect([]) == []

    def test_detectors_have_contract_default_thresholds(self) -> None:
        """AC-2, AC-3, AC-5: пороги по умолчанию совпадают с таблицей порогов."""
        exactly_30 = make_review("rev-30", words(30))
        only_29 = make_review("rev-29", words(29))
        assert [f.review_id for f in TooShort().detect([exactly_30, only_29])] == ["rev-29"]

        exactly_60 = make_review("rev-60", seconds_spent=60)
        only_59 = make_review("rev-59", seconds_spent=59)
        assert [f.review_id for f in TooFast().detect([exactly_60, only_59])] == ["rev-59"]

        # Джаккард 3/5 = 0.6 — порог по умолчанию включительный (решение человека от 2026-11-04).
        first = make_review("rev-a", words(7))
        second = make_review("rev-b", words(9))
        assert {f.review_id for f in CopyPaste().detect([first, second])} == {"rev-a", "rev-b"}

        # Джаккард 4/7 ≈ 0.57 — ниже порога по умолчанию.
        third = make_review("rev-c", words(8))
        fourth = make_review("rev-d", words(11))
        assert CopyPaste().detect([third, fourth]) == []


# ---------------------------------------------------------------- AC-1: normalize


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ПРИВЕТ Мир", "привет мир"),
            ("ёлка Ёж ещё", "елка еж еще"),
            ("Да, нет. Может!", "да нет может"),
            ("  много \t\n  пробелов здесь  ", "много пробелов здесь"),
            ("что-то", "что то"),
            ("слово,слово", "слово слово"),
            ("«кавычки» — тире… (скобки) [ещё]", "кавычки тире скобки еще"),
            ("snake_case", "snake case"),
            ("версия 3.13 и 100%", "версия 3 13 и 100"),
            ("Python3 и tmp2", "python3 и tmp2"),
        ],
    )
    def test_normalizes_case_yo_punctuation_and_spaces(self, raw: str, expected: str) -> None:
        """AC-1: нижний регистр, ё→е, пунктуация заменяется пробелом, цифры сохраняются."""
        assert normalize(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "\n\t", "...", "!?,.:;—-()«»", " - - - ", "_"])
    def test_empty_or_punctuation_only_gives_empty_string(self, raw: str) -> None:
        """AC-1: пустой вход и только пунктуация дают пустую строку."""
        assert normalize(raw) == ""

    @pytest.mark.parametrize(
        "raw", ["Ещё РАЗ, что-то  такое!", "", "...", "a_b-c 12,5", "Ёж\nи\tёлка"]
    )
    def test_is_idempotent(self, raw: str) -> None:
        """AC-1: повторная нормализация ничего не меняет."""
        once = normalize(raw)
        assert normalize(once) == once


class TestNormalizeInvisibleCharacters:
    @pytest.mark.parametrize(
        "mark",
        ["\u00ad", "\u200b", "\u200d", "\ufeff", "\u0301"],
        ids=["soft-hyphen", "zero-width-space", "zero-width-joiner", "bom", "acute-accent"],
    )
    def test_invisible_character_does_not_break_word(self, mark: str) -> None:
        """AC-1: мягкий перенос, нулевая ширина, BOM и ударение не разрывают слово."""
        assert normalize(f"алго{mark}ритм") == "алгоритм"
        assert normalize(f"{mark}быстрый алго{mark}ритм сорти{mark}ровки{mark}") == (
            "быстрый алгоритм сортировки"
        )

    def test_accented_word_in_quotes(self) -> None:
        """AC-1: «алго́ритм» с ударением U+0301 и в кавычках даёт алгоритм."""
        assert normalize("«алго\u0301ритм»") == "алгоритм"

    @pytest.mark.parametrize(
        ("decomposed", "expected"),
        [("и\u0306ка", "йка"), ("е\u0308лка", "елка"), ("Е\u0308\u0301ж", "еж")],
    )
    def test_decomposed_letters_survive_mark_removal(self, decomposed: str, expected: str) -> None:
        """AC-1: удаление ударения не портит разложенные й и ё: й остаётся, ё становится е."""
        assert normalize(decomposed) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "алго\u00adритм",
            "алго\u200bритм",
            "алго\u200dритм",
            "\ufeffалгоритм",
            "«алго\u0301ритм»",
            "\u00ad\u200b\u200d\ufeff\u0301",
            "и\u0306 е\u0308 Е\u0308\u0301",
            "и\u00ad\u0306",
            "е\u200b\u0308лка",
            "\u0130stanbul",
            "\u1112\u200b\u1161",  # чамо становятся соседними только после удаления U+200B
        ],
    )
    def test_is_idempotent_on_invisible_characters(self, raw: str) -> None:
        """AC-1: повторная нормализация строк с невидимыми символами ничего не меняет."""
        once = normalize(raw)
        assert normalize(once) == once


# ---------------------------------------------------------------- AC-2: TooShort


class TestTooShort:
    def test_exactly_threshold_words_not_flagged(self) -> None:
        """AC-2: ровно 30 значимых слов — флага нет."""
        assert TooShort(min_words=30).detect([make_review(comment=words(30))]) == []

    def test_one_below_threshold_flagged(self) -> None:
        """AC-2: 29 значимых слов — флаг."""
        flags = TooShort(min_words=30).detect([make_review("rev-29", words(29))])
        assert [(f.review_id, f.detector) for f in flags] == [("rev-29", "too_short")]

    def test_stop_words_on_top_of_30_do_not_flag(self) -> None:
        """AC-2, решение 2: 30 значимых и стоп-слова сверху — флага нет."""
        comment = words(30) + " " + " ".join(STOP_WORDS * 5)
        assert TooShort(min_words=30).detect([make_review(comment=comment)]) == []

    @pytest.mark.parametrize("stop_repeats", [1, 10, 200])
    def test_stop_words_do_not_count_towards_threshold(self, stop_repeats: int) -> None:
        """AC-2, решение 2: 29 значимых и любое число стоп-слов — флаг."""
        comment = " ".join(STOP_WORDS * stop_repeats) + " " + words(29)
        assert len(TooShort(min_words=30).detect([make_review(comment=comment)])) == 1

    def test_stop_words_are_recognized_after_normalize(self) -> None:
        """AC-2, решение 2: стоп-слова отбрасываются после normalize, регистр не важен."""
        comment = words(29) + " И, В. НА! Не? ЧТО"
        assert len(TooShort(min_words=30).detect([make_review(comment=comment)])) == 1

    def test_only_stop_words_flagged(self) -> None:
        """AC-2, решение 2: текст из одних стоп-слов не содержит значимых слов."""
        comment = " ".join(STOP_WORDS * 40)
        assert len(TooShort(min_words=30).detect([make_review(comment=comment)])) == 1

    def test_standalone_punctuation_is_not_a_word(self) -> None:
        """AC-2, решение 2: отдельно стоящие тире и знаки не считаются словами."""
        comment = words(29) + " — ... - !!! ,"
        assert len(TooShort(min_words=30).detect([make_review(comment=comment)])) == 1

    def test_punctuation_without_spaces_splits_words(self) -> None:
        """AC-2, решение 1: слова считаются после normalize, запятая разделяет их и без пробела."""
        comment = ",".join(NOUNS[:30])
        assert TooShort(min_words=30).detect([make_review(comment=comment)]) == []

    @pytest.mark.parametrize("comment", ["", "   ", "...", "\n"])
    def test_empty_comment_flagged(self, comment: str) -> None:
        """AC-2, решение 2: пустой комментарий помечается."""
        assert len(TooShort(min_words=30).detect([make_review(comment=comment)])) == 1

    def test_threshold_is_configurable(self) -> None:
        """AC-2: порог настраивается параметром min_words."""
        review = make_review(comment=words(5))
        assert TooShort(min_words=5).detect([review]) == []
        assert len(TooShort(min_words=6).detect([review])) == 1

    def test_only_short_reviews_flagged_in_a_batch(self) -> None:
        """AC-2: в наборе помечаются только короткие рецензии."""
        reviews = [make_review("rev-long", words(35)), make_review("rev-short", "норм")]
        assert [f.review_id for f in TooShort(min_words=30).detect(reviews)] == ["rev-short"]


class TestTooShortStopWordList:
    """Полный список стоп-слов намеренно не закреплён: контракт только про бесспорные слова."""

    @pytest.mark.parametrize("stop_word", ["при", "бы", "или", "до", "же"])
    def test_undisputed_stop_word_is_not_significant(self, stop_word: str) -> None:
        """AC-2, решение 2: служебное слово не добирает 29 значимых слов до порога 30."""
        comment = f"{words(29)} {stop_word}"
        assert len(TooShort(min_words=30).detect([make_review(comment=comment)])) == 1

    def test_undisputed_stop_words_together_and_in_upper_case(self) -> None:
        """AC-2, решение 2: те же слова не считаются и вместе, и в верхнем регистре."""
        comment = f"{words(29)} при бы или до же ПРИ БЫ ИЛИ ДО ЖЕ"
        assert len(TooShort(min_words=30).detect([make_review(comment=comment)])) == 1

    def test_significant_word_in_same_position_reaches_threshold(self) -> None:
        """AC-2, решение 2: контроль: значимое слово на том же месте снимает флаг."""
        assert TooShort(min_words=30).detect([make_review(comment=f"{words(29)} алгебра")]) == []


# ---------------------------------------------------------------- AC-3: CopyPaste


class TestCopyPaste:
    def test_flags_both_reviews_of_a_pair_between_reviewers(self) -> None:
        """AC-3: копипаста между разными рецензентами — флаг на обеих рецензиях."""
        reviews = [
            make_review("rev-a", words(20), reviewer_id="petrov7"),
            make_review("rev-b", words(20), reviewer_id="sidorov8"),
            make_review("rev-c", words(20, start=20), reviewer_id="orlova9"),
        ]
        flags = flags_by_id(CopyPaste(threshold=0.8).detect(reviews))
        assert set(flags) == {"rev-a", "rev-b"}
        assert all(flag.detector == "copy_paste" for flag in flags.values())
        assert flags["rev-a"].score == pytest.approx(1.0)

    def test_flags_both_reviews_of_a_pair_within_one_reviewer(self) -> None:
        """AC-3: копипаста внутри одного рецензента — флаг на обеих рецензиях."""
        reviews = [
            make_review("rev-a", words(20), reviewer_id="petrov7"),
            make_review("rev-b", words(20), reviewer_id="petrov7"),
        ]
        assert set(flags_by_id(CopyPaste(threshold=0.8).detect(reviews))) == {"rev-a", "rev-b"}

    def test_unrelated_reviews_not_flagged(self) -> None:
        """AC-3: несвязанные тексты не помечаются."""
        reviews = [make_review("rev-a", words(20)), make_review("rev-b", words(20, start=20))]
        assert CopyPaste(threshold=0.8).detect(reviews) == []

    def test_comparison_happens_after_normalize(self) -> None:
        """AC-3, решение 3: регистр, пунктуация и ё/е не влияют на сравнение."""
        first = "Ещё раз, автор: написал отчёт — и всё! Выводы верные."
        second = "еще раз автор написал отчет и все выводы верные"
        flags = flags_by_id(
            CopyPaste(threshold=0.8).detect(
                [make_review("rev-a", first), make_review("rev-b", second)]
            )
        )
        assert set(flags) == {"rev-a", "rev-b"}
        assert flags["rev-a"].score == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "comment", ["", "...", "норм", "хорошая работа", "очень хорошая работа молодец"]
    )
    def test_identical_reviews_shorter_than_five_words_not_flagged(self, comment: str) -> None:
        """AC-3, решение 3: короче 5 слов нет 5-грамм, совпадения нет и для одинаковых текстов."""
        reviews = [make_review("rev-a", comment), make_review("rev-b", comment)]
        assert CopyPaste(threshold=0.8).detect(reviews) == []

    def test_short_review_is_not_a_match_for_a_long_one(self) -> None:
        """AC-3, решение 3: рецензия без 5-грамм не совпадает и с длинной рецензией."""
        reviews = [make_review("rev-a", words(4)), make_review("rev-b", words(20))]
        assert CopyPaste(threshold=0.1).detect(reviews) == []

    def test_identical_reviews_of_exactly_five_words_flagged(self) -> None:
        """AC-3, решение 3: граница длины — ровно 5 слов уже дают одну 5-грамму."""
        reviews = [make_review("rev-a", words(5)), make_review("rev-b", words(5))]
        assert set(flags_by_id(CopyPaste(threshold=0.8).detect(reviews))) == {"rev-a", "rev-b"}

    def test_stop_words_are_part_of_five_grams(self) -> None:
        """AC-3, решение 3: 5-граммы строятся после normalize, стоп-слова не выбрасываются."""
        comment = " ".join(STOP_WORDS)
        reviews = [make_review("rev-a", comment), make_review("rev-b", comment)]
        assert set(flags_by_id(CopyPaste(threshold=0.8).detect(reviews))) == {"rev-a", "rev-b"}

    def test_threshold_is_inclusive_on_exact_value(self) -> None:
        """AC-3, решение 3: 8 и 9 слов — 4 общие 5-граммы из 5, Jaccard = 0.8 → флаг."""
        reviews = [make_review("rev-a", words(8)), make_review("rev-b", words(9))]
        flags = flags_by_id(CopyPaste(threshold=0.8).detect(reviews))
        assert set(flags) == {"rev-a", "rev-b"}
        assert flags["rev-a"].score == pytest.approx(0.8)
        assert flags["rev-b"].score == pytest.approx(0.8)

    def test_value_below_threshold_not_flagged(self) -> None:
        """AC-3: 7 и 8 слов — 3 общие 5-граммы из 4, Jaccard = 0.75 < 0.8 → флага нет."""
        reviews = [make_review("rev-a", words(7)), make_review("rev-b", words(8))]
        assert CopyPaste(threshold=0.8).detect(reviews) == []

    def test_threshold_is_configurable(self) -> None:
        """AC-3: порог настраивается, и 0.75 включителен при Jaccard = 3/4."""
        reviews = [make_review("rev-a", words(7)), make_review("rev-b", words(8))]
        flags = flags_by_id(CopyPaste(threshold=0.75).detect(reviews))
        assert flags["rev-a"].score == pytest.approx(0.75)
        assert CopyPaste(threshold=0.76).detect(reviews) == []

    def test_five_grams_are_compared_as_sets(self) -> None:
        """AC-3: Jaccard считается по множествам, повторы 5-грамм не влияют на значение."""
        cycle = NOUNS[:5]
        twice = " ".join(cycle + cycle)  # 5 разных 5-грамм, одна повторяется
        nearly_twice = " ".join(cycle + cycle[:4])  # те же 5 разных 5-грамм
        flags = flags_by_id(
            CopyPaste(threshold=0.8).detect(
                [make_review("rev-a", twice), make_review("rev-b", nearly_twice)]
            )
        )
        assert flags["rev-a"].score == pytest.approx(1.0)

    def test_review_is_not_compared_with_itself(self) -> None:
        """AC-3, решение 3: единственная рецензия не совпадает сама с собой."""
        assert CopyPaste(threshold=0.8).detect([make_review("rev-a", words(20))]) == []

    def test_reason_names_second_review_and_percent(self) -> None:
        """AC-3: в reason указаны review_id второй рецензии и процент совпадения."""
        reviews = [make_review("rev-a", words(8)), make_review("rev-b", words(9))]
        flags = flags_by_id(CopyPaste(threshold=0.8).detect(reviews))
        assert "rev-b" in flags["rev-a"].reason
        assert "rev-a" in flags["rev-b"].reason
        assert re.search(r"\b80(?:[.,]0+)?\s*%", flags["rev-a"].reason), flags["rev-a"].reason

    def test_one_flag_per_review_with_best_match(self) -> None:
        """Решение 3: один флаг на рецензию, и он указывает на лучшее совпадение."""
        base = NOUNS[:20]
        near = " ".join([*base, NOUNS[20]])  # с базой 16/17 ≈ 0.94
        far = " ".join([*base, *NOUNS[21:25]])  # с базой 16/20 = 0.8, с near 16/21 ≈ 0.76
        reviews = [
            make_review("rev-far", far),
            make_review("rev-base", " ".join(base)),
            make_review("rev-near", near),
        ]
        flags = flags_by_id(CopyPaste(threshold=0.8).detect(reviews))
        assert set(flags) == {"rev-far", "rev-base", "rev-near"}

        assert flags["rev-base"].score == pytest.approx(16 / 17)
        assert "rev-near" in flags["rev-base"].reason
        assert "rev-far" not in flags["rev-base"].reason

        assert flags["rev-near"].score == pytest.approx(16 / 17)
        assert "rev-base" in flags["rev-near"].reason

        assert flags["rev-far"].score == pytest.approx(0.8)
        assert "rev-base" in flags["rev-far"].reason
        assert "rev-near" not in flags["rev-far"].reason

    @pytest.mark.parametrize("order", list(itertools.permutations(["rev-c", "rev-a", "rev-b"])))
    def test_tie_is_resolved_to_smallest_review_id(self, order: tuple[str, ...]) -> None:
        """Решение 3: при равном Jaccard выбирается наименьший review_id при любом порядке."""
        reviews = [make_review(review_id, words(20)) for review_id in order]
        flags = flags_by_id(CopyPaste(threshold=0.8).detect(reviews))
        assert "rev-b" in flags["rev-a"].reason
        assert "rev-c" not in flags["rev-a"].reason
        assert "rev-a" in flags["rev-b"].reason
        assert "rev-c" not in flags["rev-b"].reason
        assert "rev-a" in flags["rev-c"].reason
        assert "rev-b" not in flags["rev-c"].reason


def exact_jaccard(first: str, second: str) -> Fraction:
    """Точный Jaccard по 5-граммам уже нормализованных текстов, независимо от реализации."""

    def grams(text: str) -> set[tuple[str, ...]]:
        tokens = text.split()
        return {tuple(tokens[i : i + 5]) for i in range(len(tokens) - 4)}

    first_grams, second_grams = grams(first), grams(second)
    return Fraction(len(first_grams & second_grams), len(first_grams | second_grams))


def reason_percents(flag: Flag) -> list[str]:
    """Все числа с процентами в reason."""
    return re.findall(r"(\d+(?:[.,]\d+)?)\s*%", flag.reason)


class TestCopyPasteReasonPercent:
    @pytest.mark.parametrize("length", [204, 250, 400])
    def test_percent_is_99_when_jaccard_rounds_to_100(self, length: int) -> None:
        """AC-3: Jaccard ≥ 0.995, но не 1: округление дало бы 100, в reason показывается 99."""
        tokens = [f"слово{i}" for i in range(length)]
        first = " ".join(tokens)
        second = f"{first} добавка"

        jaccard = exact_jaccard(first, second)
        assert jaccard == Fraction(length - 4, length - 3)  # от 200 различных 5-грамм
        assert round(jaccard * 100) == 100  # без отдельного правила здесь было бы 100
        assert jaccard < 1

        flags = flags_by_id(
            CopyPaste().detect([make_review("rev-a", first), make_review("rev-b", second)])
        )
        assert set(flags) == {"rev-a", "rev-b"}
        for flag in flags.values():
            assert flag.score == pytest.approx(float(jaccard))
            assert flag.score < 1.0
            assert reason_percents(flag) == ["99"], flag.reason

    def test_percent_is_100_when_five_grams_match_completely(self) -> None:
        """AC-3: при полном совпадении текстов в reason показывается 100."""
        comment = " ".join(f"слово{i}" for i in range(250))
        flags = flags_by_id(
            CopyPaste().detect([make_review("rev-a", comment), make_review("rev-b", comment)])
        )
        assert set(flags) == {"rev-a", "rev-b"}
        for flag in flags.values():
            assert flag.score == 1.0
            assert reason_percents(flag) == ["100"], flag.reason

    def test_percent_is_100_when_only_sets_of_five_grams_match(self) -> None:
        """AC-3: 100 определяется множествами 5-грамм: тексты разной длины с равными множествами."""
        cycle = NOUNS[:5]
        first = " ".join(cycle + cycle)
        second = " ".join(cycle + cycle[:4])
        assert first != second
        assert exact_jaccard(first, second) == 1

        flags = flags_by_id(
            CopyPaste().detect([make_review("rev-a", first), make_review("rev-b", second)])
        )
        assert set(flags) == {"rev-a", "rev-b"}
        for flag in flags.values():
            assert reason_percents(flag) == ["100"], flag.reason


class TestThresholdValidation:
    @pytest.mark.parametrize("threshold", INVALID_THRESHOLDS, ids=repr)
    def test_copy_paste_rejects_threshold_out_of_range(self, threshold: float) -> None:
        """Решение 6: порог CopyPaste вне 0 < T <= 1, включая nan и inf, даёт ValueError."""
        with pytest.raises(ValueError, match=r"\S"):
            CopyPaste(threshold=threshold)

    @pytest.mark.parametrize("threshold", INVALID_THRESHOLDS, ids=repr)
    def test_config_rejects_threshold_out_of_range(self, threshold: float) -> None:
        """Решение 6: порог в QualityConfig вне 0 < T <= 1, включая nan и inf, даёт ValueError."""
        with pytest.raises(ValueError, match=r"\S"):
            QualityConfig(copy_threshold=threshold)

    def test_threshold_one_is_valid_and_means_full_match(self) -> None:
        """Решение 6: 1.0 допустим: помечается только полное совпадение множеств 5-грамм."""
        reviews = [
            make_review("rev-a", words(20)),
            make_review("rev-b", words(20)),
            make_review("rev-c", words(21)),
        ]
        expected = {"rev-a", "rev-b"}
        assert {f.review_id for f in CopyPaste(threshold=1.0).detect(reviews)} == expected

        config = QualityConfig(enabled=frozenset({"copy_paste"}), copy_threshold=1.0)
        assert config.copy_threshold == 1.0
        assert {f.review_id for f in run_all(reviews, config)} == expected

    @pytest.mark.parametrize(
        "enabled",
        [{"unknown"}, {"too_short", "unknown"}, {"copypaste"}, {""}],
        ids=["unknown", "mixed", "typo", "empty-name"],
    )
    def test_config_rejects_unknown_detector_name(self, enabled: set[str]) -> None:
        """Решение 6: неизвестное имя в enabled даёт ValueError, а не молчаливое отключение."""
        with pytest.raises(ValueError, match=r"\S"):
            QualityConfig(enabled=frozenset(enabled))


# ---------------------------------------------------------------- AC-4: UniformScores


class TestUniformScores:
    @pytest.mark.parametrize(
        "scores", [(5, 5, 5), (3, 3, 3, 3), (1, 1, 1, 1, 1), (0, 0, 0)], ids=str
    )
    def test_equal_scores_on_three_or_more_criteria_flagged(self, scores: tuple[int, ...]) -> None:
        """AC-4: все оценки равны при ≥ 3 критериях — флаг, в том числе для нулей."""
        flags = UniformScores().detect([make_review("rev-1", scores=scores)])
        assert [(f.review_id, f.detector) for f in flags] == [("rev-1", "uniform_scores")]

    @pytest.mark.parametrize(
        "scores",
        [(), (5,), (5, 5), (5, 5, 4), (4, 5, 5), (5, 4, 5), (1, 2, 3), (3, 3, 3, 2)],
        ids=str,
    )
    def test_too_few_criteria_or_any_difference_not_flagged(self, scores: tuple[int, ...]) -> None:
        """AC-4: меньше 3 критериев, пустые scores или хотя бы одна разница — флага нет."""
        assert UniformScores().detect([make_review(scores=scores)]) == []


# ---------------------------------------------------------------- AC-5: TooFast


class TestTooFast:
    def test_exactly_min_seconds_not_flagged(self) -> None:
        """AC-5: ровно min_seconds — флага нет."""
        assert TooFast(min_seconds=60).detect([make_review(seconds_spent=60)]) == []

    @pytest.mark.parametrize("seconds", [59, 1, 0])
    def test_below_min_seconds_flagged(self, seconds: int) -> None:
        """AC-5: меньше порога — флаг, включая 0 секунд."""
        flags = TooFast(min_seconds=60).detect([make_review("rev-1", seconds_spent=seconds)])
        assert [(f.review_id, f.detector) for f in flags] == [("rev-1", "too_fast")]

    def test_unknown_time_not_flagged(self) -> None:
        """AC-5: seconds_spent=None — флага нет."""
        assert TooFast(min_seconds=60).detect([make_review(seconds_spent=None)]) == []

    def test_threshold_is_configurable(self) -> None:
        """AC-5: порог настраивается параметром min_seconds."""
        review = make_review(seconds_spent=100)
        assert TooFast(min_seconds=100).detect([review]) == []
        assert len(TooFast(min_seconds=101).detect([review])) == 1


class TestTooFastNegativeTime:
    @pytest.mark.parametrize("seconds", [-1, -5, -3600])
    def test_negative_time_is_flagged_without_negative_number_in_reason(self, seconds: int) -> None:
        """AC-5, решение 5: отрицательное время — флаг, в reason нет отрицательного числа."""
        flags = TooFast(min_seconds=60).detect([make_review("rev-1", seconds_spent=seconds)])
        assert [(f.review_id, f.detector) for f in flags] == [("rev-1", "too_fast")]
        assert flags[0].reason.strip()
        assert not re.search(r"[-−–—]\s*\d", flags[0].reason), flags[0].reason


# ---------------------------------------------------------------- общие требования к флагам

MARKER = "ivanov0"
OTHER_MARKER = "sidorova5"


def triggering_reviews() -> list[ReviewText]:
    """Набор, на котором срабатывают все четыре детектора."""
    return [
        make_review("rev-a", "норм", reviewer_id=MARKER, scores=(5, 5, 5), seconds_spent=0),
        make_review("rev-b", "норм", reviewer_id=OTHER_MARKER, scores=(4, 4, 4), seconds_spent=59),
        make_review("rev-c", words(40), reviewer_id=MARKER),
        make_review("rev-d", words(40), reviewer_id=OTHER_MARKER),
    ]


ALL_DETECTORS: list[Detector] = [
    TooShort(min_words=30),
    CopyPaste(threshold=0.8),
    UniformScores(),
    TooFast(min_seconds=60),
]


class TestFlagQuality:
    @pytest.mark.parametrize("detector", ALL_DETECTORS, ids=lambda d: d.name)
    def test_reason_does_not_reveal_reviewer(self, detector: Detector) -> None:
        """Инвариант анонимности, решение 4: reason не содержит reviewer_id ни одной из сторон."""
        flags = detector.detect(triggering_reviews())
        assert flags, "Набор должен вызывать срабатывание детектора"
        for flag in flags:
            assert MARKER not in flag.reason
            assert OTHER_MARKER not in flag.reason

    @pytest.mark.parametrize("detector", ALL_DETECTORS, ids=lambda d: d.name)
    def test_score_and_reason_are_well_formed(self, detector: Detector) -> None:
        """Решение 5: score в [0, 1], reason непустой и содержит кириллицу, detector — имя."""
        flags = detector.detect(triggering_reviews())
        assert flags
        for flag in flags:
            assert 0.0 <= flag.score <= 1.0
            assert flag.reason.strip()
            assert re.search(r"[А-Яа-яЁё]", flag.reason), flag.reason
            assert flag.detector == detector.name

    def test_score_stays_in_range_on_extreme_inputs(self) -> None:
        """Решение 5: score в [0, 1] и при пустом тексте, и при отрицательном времени."""
        reviews = [
            make_review("rev-empty", "", seconds_spent=0),
            make_review("rev-skew", words(40), seconds_spent=-5),
        ]
        flags = TooShort().detect(reviews) + TooFast().detect(reviews)
        assert {f.review_id for f in flags} == {"rev-empty", "rev-skew"}
        assert all(0.0 <= flag.score <= 1.0 for flag in flags)


class TestRuleScoreIsExactlyOne:
    """Решение 5: у детекторов-правил score равен 1.0 независимо от масштаба нарушения."""

    @pytest.mark.parametrize("comment", ["", "норм", words(29)], ids=["empty", "one", "29"])
    def test_too_short(self, comment: str) -> None:
        """Решение 5: TooShort даёт ровно 1.0 при любой длине комментария ниже порога."""
        flags = TooShort(min_words=30).detect([make_review(comment=comment)])
        assert [flag.score for flag in flags] == [1.0]

    @pytest.mark.parametrize("seconds", [-5, 0, 1, 59])
    def test_too_fast(self, seconds: int) -> None:
        """Решение 5: TooFast даёт ровно 1.0 при любом времени ниже порога."""
        flags = TooFast(min_seconds=60).detect([make_review(seconds_spent=seconds)])
        assert [flag.score for flag in flags] == [1.0]

    @pytest.mark.parametrize("scores", [(0, 0, 0), (5, 5, 5), (3, 3, 3, 3, 3)], ids=str)
    def test_uniform_scores(self, scores: tuple[int, ...]) -> None:
        """Решение 5: UniformScores даёт ровно 1.0 при любой оценке и любом числе критериев."""
        flags = UniformScores().detect([make_review(scores=scores)])
        assert [flag.score for flag in flags] == [1.0]


class TestReprDoesNotRevealReviewer:
    def test_review_text_repr_hides_reviewer_and_comment(self) -> None:
        """Инвариант анонимности: repr(ReviewText) не содержит reviewer_id и comment."""
        review = make_review("rev-visible", "маркерныйтекст рецензии", reviewer_id=MARKER)
        assert MARKER not in repr(review)
        assert "маркерныйтекст" not in repr(review)
        assert "rev-visible" in repr(review)

    @pytest.mark.parametrize("detector", ALL_DETECTORS, ids=lambda d: d.name)
    def test_flag_repr_hides_reviewer(self, detector: Detector) -> None:
        """Инвариант анонимности: repr(Flag) реального срабатывания не содержит reviewer_id."""
        flags = detector.detect(triggering_reviews())
        assert flags
        for flag in flags:
            assert MARKER not in repr(flag)
            assert OTHER_MARKER not in repr(flag)


# ---------------------------------------------------------------- AC-6: run_all


class TestRunAll:
    def test_config_defaults_match_threshold_table(self) -> None:
        """AC-6: QualityConfig по умолчанию включает все детекторы с порогами из таблицы."""
        config = QualityConfig()
        assert config.enabled == frozenset(DETECTOR_NAMES)
        assert isinstance(config.enabled, frozenset)
        assert config.min_words == 30
        assert config.copy_threshold == pytest.approx(0.6)
        assert config.min_seconds == 60

    def test_config_is_frozen(self) -> None:
        """AC-6: QualityConfig — frozen dataclass."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            QualityConfig().min_words = 1  # type: ignore[misc]

    def test_combines_flags_of_all_detectors_by_default(self) -> None:
        """AC-6: run_all без конфига объединяет флаги всех детекторов."""
        pairs = {(f.review_id, f.detector) for f in run_all(triggering_reviews())}
        assert pairs == {
            ("rev-a", "too_short"),
            ("rev-a", "uniform_scores"),
            ("rev-a", "too_fast"),
            ("rev-b", "too_short"),
            ("rev-b", "uniform_scores"),
            ("rev-b", "too_fast"),
            ("rev-c", "copy_paste"),
            ("rev-d", "copy_paste"),
        }

    def test_returns_list_of_flags(self) -> None:
        """AC-6: run_all возвращает список флагов."""
        result = run_all(triggering_reviews())
        assert isinstance(result, list)
        assert all(isinstance(flag, Flag) for flag in result)

    def test_empty_input_gives_empty_list(self) -> None:
        """AC-6, решение 6: пустой вход даёт пустой список."""
        assert run_all([]) == []
        assert run_all([], QualityConfig()) == []

    @pytest.mark.parametrize("disabled", sorted(DETECTOR_NAMES))
    def test_disabled_detector_gives_no_flags(self, disabled: str) -> None:
        """AC-6, решение 6: отключённый детектор молчит, остальные продолжают работать."""
        config = QualityConfig(enabled=frozenset(DETECTOR_NAMES - {disabled}))
        detectors = {f.detector for f in run_all(triggering_reviews(), config)}
        assert detectors == DETECTOR_NAMES - {disabled}

    @pytest.mark.parametrize("only", sorted(DETECTOR_NAMES))
    def test_single_enabled_detector(self, only: str) -> None:
        """AC-6: при одном включённом детекторе флаги только от него."""
        config = QualityConfig(enabled=frozenset({only}))
        assert {f.detector for f in run_all(triggering_reviews(), config)} == {only}

    def test_all_disabled_gives_no_flags(self) -> None:
        """AC-6: все детекторы отключены — флагов нет."""
        assert run_all(triggering_reviews(), QualityConfig(enabled=frozenset())) == []

    def test_thresholds_are_taken_from_config(self) -> None:
        """AC-6: пороги min_words, copy_threshold, min_seconds берутся из конфига."""
        reviews = [
            make_review("rev-a", words(7), seconds_spent=100),
            make_review("rev-b", words(8), seconds_spent=100),
        ]
        strict = QualityConfig(min_words=8, copy_threshold=0.75, min_seconds=101)
        assert {(f.review_id, f.detector) for f in run_all(reviews, strict)} == {
            ("rev-a", "too_short"),
            ("rev-a", "copy_paste"),
            ("rev-b", "copy_paste"),
            ("rev-a", "too_fast"),
            ("rev-b", "too_fast"),
        }
        lenient = QualityConfig(min_words=7, copy_threshold=0.76, min_seconds=100)
        assert run_all(reviews, lenient) == []

    def test_result_does_not_depend_on_input_order(self) -> None:
        """AC-6, решение 6: результат не зависит от порядка рецензий."""
        reviews = [*triggering_reviews(), make_review("rev-e", words(40))]
        expected = canonical(run_all(reviews))
        for permutation in itertools.permutations(reviews):
            assert canonical(run_all(list(permutation))) == expected

    def test_input_is_not_mutated_and_sequence_is_accepted(self) -> None:
        """AC-6, решение 6: вход не изменяется; подходит любая Sequence."""
        reviews = list(reversed(triggering_reviews()))
        before = list(reviews)
        from_list = run_all(reviews)
        assert reviews == before
        assert canonical(run_all(tuple(reviews))) == canonical(from_list)

    def test_global_random_state_is_preserved(self) -> None:
        """Решение 6: run_all не меняет глобальное состояние random."""
        random.seed(20261104)
        before = random.getstate()
        run_all(triggering_reviews())
        assert random.getstate() == before


# ---------------------------------------------------------------- AC-8: скорость и чистота


COPY_PASTE_TIMING_SCRIPT = """
import json
import random
import time

from apps.quality.detectors import CopyPaste, ReviewText

rng = random.Random(11)
vocabulary = [f"слово{i}" for i in range(2000)]
comments = [" ".join(rng.choices(vocabulary, k=150)) for _ in range(300)]
comments[17] = comments[250]
reviews = [
    ReviewText(
        review_id=f"rev-{i:03d}",
        reviewer_id=f"reviewer-{i}",
        comment=comment,
        scores=(1, 2, 3),
        seconds_spent=None,
    )
    for i, comment in enumerate(comments)
]
started = time.perf_counter()
flags = CopyPaste(threshold=0.8).detect(reviews)
elapsed = time.perf_counter() - started
print(json.dumps({"elapsed": elapsed, "flagged": sorted(f.review_id for f in flags)}))
"""


@pytest.mark.slow
def test_copy_paste_is_fast_on_independent_reviews() -> None:
    """AC-8: 300 рецензий по 150 слов обрабатываются меньше 2 с без потери находок.

    Замер идёт в отдельном процессе: в `make check` тесты выполняются параллельно
    и с покрытием, а трассировка замедляет код в разы и делает результат случайным.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("COV")}
    completed = subprocess.run(
        [sys.executable, "-c", COPY_PASTE_TIMING_SCRIPT],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(completed.stdout)

    assert result["elapsed"] < 2.0, f"CopyPaste занял {result['elapsed']:.2f} с"
    assert result["flagged"] == ["rev-017", "rev-250"]


def _pure_python_files() -> list[Path]:
    detectors_dir = ROOT / "apps" / "quality" / "detectors"
    return sorted(detectors_dir.rglob("*.py")) + [ROOT / "apps" / "quality" / "__init__.py"]


def _absolute_imports(path: Path) -> list[str]:
    """Абсолютные имена всех импортов файла, включая разрешённые относительные."""
    package = list(path.relative_to(ROOT).with_suffix("").parts)
    package = package[:-1]  # каталог файла: и для модуля, и для __init__.py
    modules: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                bases = [node.module or ""]
            else:
                parent = package[: len(package) - (node.level - 1)]
                base = ".".join(parent)
                bases = (
                    [f"{base}.{node.module}"]
                    if node.module
                    else [f"{base}.{alias.name}" for alias in node.names]
                )
            modules.extend(bases)
    return modules


def test_pure_core_has_no_forbidden_imports() -> None:
    """AC-8: detectors/** и quality/__init__.py не импортируют django и apps.*, кроме quality."""
    assert (ROOT / "apps" / "quality" / "detectors" / "__init__.py").is_file()
    violations = []
    for path in _pure_python_files():
        for module in _absolute_imports(path):
            root = module.split(".")[0]
            is_foreign_app = root == "apps" and not (
                module == "apps.quality" or module.startswith("apps.quality.")
            )
            if root == "django" or is_foreign_app:
                violations.append(f"{path.relative_to(ROOT)}: {module}")
    assert not violations, "Запрещённые импорты: " + ", ".join(violations)


def test_importing_core_does_not_load_django() -> None:
    """AC-8: импорт ядра в чистом процессе не подгружает Django и транзитивно."""
    code = "import sys, apps.quality.detectors; sys.exit('django' in sys.modules)"
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr or "Импорт ядра подгрузил django"
