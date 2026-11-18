"""Инварианты детекторов халтурных рецензий (T-011): property-тесты на hypothesis."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from apps.quality.detectors import (
    CopyPaste,
    Flag,
    ReviewText,
    TooFast,
    TooShort,
    UniformScores,
    normalize,
    run_all,
)

PROPERTY_SETTINGS = settings(max_examples=200, deadline=None)

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
    "отчёт",
    "учёт",
]
STOP_WORDS = ["и", "в", "на", "не", "что"]

# Разделители содержат пробел или знак, который normalize заменит пробелом.
SEPARATORS = [" ", ", ", ". ", " — ", "! ", "... ", ": ", "\n", "; ", " (", ") ", "-", ",", " « "]
CASE_CHANGES = [str.lower, str.upper, str.capitalize]

text_like_reviews = st.one_of(
    st.text(),
    st.text(alphabet=" \t\n,.!?—-_«»()0123456789абвгдеёжАБВГДЕЁЖabcXYZ"),
)

# Маленький словарь, чтобы тексты часто пересекались по 5-граммам.
small_vocabulary = st.sampled_from(NOUNS[:6])
copy_words = st.lists(small_vocabulary, max_size=30)


def review(
    review_id: str,
    comment: str,
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


def canonical(flags: list[Flag]) -> list[Flag]:
    return sorted(flags, key=lambda f: (f.review_id, f.detector, f.reason, f.score))


@st.composite
def edited_copy(draw: st.DrawFn, base: list[str]) -> list[str]:
    """Копия текста с несколькими заменами и хвостом: создаёт Jaccard по всему диапазону."""
    tokens = list(base)
    if tokens:
        for _ in range(draw(st.integers(0, 3))):
            position = draw(st.integers(0, len(tokens) - 1))
            tokens[position] = draw(small_vocabulary)
    return tokens + draw(st.lists(small_vocabulary, max_size=4))


@st.composite
def related_texts(draw: st.DrawFn) -> list[list[str]]:
    """От 2 до 4 текстов, производных от одного: пары часто оказываются около порога."""
    base = draw(copy_words)
    others = [draw(edited_copy(base)) for _ in range(draw(st.integers(1, 3)))]
    return [base, *others]


def shingles(tokens: list[str]) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + 5]) for i in range(len(tokens) - 4)}


def jaccard(first: list[str], second: list[str]) -> float:
    a, b = shingles(first), shingles(second)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------- normalize


@PROPERTY_SETTINGS
@given(text_like_reviews)
def test_normalize_is_idempotent(text: str) -> None:
    """AC-1, решение 1: normalize(normalize(x)) == normalize(x)."""
    once = normalize(text)
    assert normalize(once) == once


@PROPERTY_SETTINGS
@given(text_like_reviews)
def test_normalize_gives_lowercase_words_separated_by_single_space(text: str) -> None:
    """AC-1, решение 1: результат — слова в нижнем регистре через один пробел, без ё."""
    result = normalize(text)
    assert result == " ".join(result.split(" "))
    assert result == result.strip()
    assert "  " not in result
    assert not any(ch.isspace() and ch != " " for ch in result)
    assert result == result.lower()
    assert "ё" not in result


# ---------------------------------------------------------------- too_short


@st.composite
def comment_tokens(draw: st.DrawFn) -> list[str]:
    significant = draw(st.integers(0, 45))
    stops = draw(st.lists(st.sampled_from(STOP_WORDS), max_size=30))
    return draw(st.permutations([*NOUNS[:significant], *stops]))


@st.composite
def decorated(draw: st.DrawFn) -> tuple[list[str], str]:
    """Пара: исходные токены и тот же текст с изменёнными регистром и пунктуацией."""
    tokens = draw(comment_tokens())
    pieces: list[str] = [draw(st.sampled_from(["", "«", "(", "— "]))]
    for token in tokens:
        pieces.append(draw(st.sampled_from(CASE_CHANGES))(token))
        pieces.append(draw(st.sampled_from(SEPARATORS)))
    return tokens, "".join(pieces)


@PROPERTY_SETTINGS
@given(decorated(), st.integers(1, 50))
def test_case_and_punctuation_do_not_change_too_short_flag(
    sample: tuple[list[str], str], min_words: int
) -> None:
    """AC-2, решения 1–2: регистр и пунктуация не меняют флаг too_short."""
    tokens, noisy = sample
    detector = TooShort(min_words=min_words)
    plain_flagged = bool(detector.detect([review("rev-1", " ".join(tokens))]))
    noisy_flagged = bool(detector.detect([review("rev-1", noisy)]))
    assert plain_flagged == noisy_flagged


@PROPERTY_SETTINGS
@given(comment_tokens(), st.integers(0, 60), st.integers(0, 60))
def test_too_short_is_monotonic_in_min_words(tokens: list[str], low: int, delta: int) -> None:
    """AC-2: при большем min_words флаг too_short не исчезает."""
    reviews = [review("rev-1", " ".join(tokens))]
    if TooShort(min_words=low).detect(reviews):
        assert TooShort(min_words=low + delta).detect(reviews)


@PROPERTY_SETTINGS
@given(st.integers(0, 45), st.lists(st.sampled_from(STOP_WORDS), max_size=60), st.integers(1, 50))
def test_too_short_counts_only_significant_words(
    significant: int, stops: list[str], min_words: int
) -> None:
    """AC-2, решение 2: флаг ставится тогда и только тогда, когда значимых слов меньше порога."""
    comment = " ".join([*stops, *NOUNS[:significant]])
    flagged = bool(TooShort(min_words=min_words).detect([review("rev-1", comment)]))
    assert flagged == (significant < min_words)


# ---------------------------------------------------------------- copy_paste


@PROPERTY_SETTINGS
@given(related_texts(), st.sampled_from([0.5, 0.8]))
def test_copy_paste_is_symmetric(texts: list[list[str]], threshold: float) -> None:
    """AC-3: если рецензия A помечена из-за B, то B тоже помечена."""
    reviews = [review(f"rev-{i}", " ".join(tokens)) for i, tokens in enumerate(texts)]
    flags = {f.review_id: f for f in CopyPaste(threshold=threshold).detect(reviews)}
    for flag in flags.values():
        matches = [r.review_id for r in reviews if r.review_id != flag.review_id]
        partners = [other for other in matches if other in flag.reason]
        assert partners, f"В reason не указана вторая рецензия: {flag.reason}"
        for partner in partners:
            assert partner in flags, f"{flag.review_id} помечена из-за {partner}, а та — нет"


@PROPERTY_SETTINGS
@given(related_texts(), st.sampled_from([0.5, 0.8]))
def test_copy_paste_matches_exact_jaccard_of_five_grams(
    texts: list[list[str]], threshold: float
) -> None:
    """AC-3, решение 3: флаг и score совпадают с точным Jaccard лучшего совпадения."""
    reviews = [review(f"rev-{i}", " ".join(tokens)) for i, tokens in enumerate(texts)]
    flags = {f.review_id: f for f in CopyPaste(threshold=threshold).detect(reviews)}
    for i, tokens in enumerate(texts):
        best = max(
            (jaccard(tokens, other) for j, other in enumerate(texts) if j != i),
            default=0.0,
        )
        review_id = f"rev-{i}"
        assert (review_id in flags) == (best >= threshold), (review_id, best)
        if review_id in flags:
            assert abs(flags[review_id].score - best) < 1e-9


# ---------------------------------------------------------------- run_all и общие инварианты


@st.composite
def arbitrary_reviews(draw: st.DrawFn) -> list[ReviewText]:
    count = draw(st.integers(0, 6))
    reviews = []
    base = draw(copy_words)
    for i in range(count):
        tokens = draw(st.one_of(st.just(base), edited_copy(base), copy_words))
        reviews.append(
            review(
                f"rev-{i}",
                " ".join(tokens),
                reviewer_id=draw(st.sampled_from(["ivanov0", "sidorova5"])),
                scores=tuple(draw(st.lists(st.integers(0, 5), max_size=5))),
                seconds_spent=draw(st.one_of(st.none(), st.integers(-10, 7200))),
            )
        )
    return reviews


@PROPERTY_SETTINGS
@given(arbitrary_reviews(), st.integers(1, 3600), st.integers(1, 100), st.floats(0.01, 1.0))
def test_every_flag_is_well_formed(
    reviews: list[ReviewText], min_seconds: int, min_words: int, threshold: float
) -> None:
    """Решения 4–5: score в [0, 1], reason на русском и без reviewer_id при любых данных."""
    flags = [
        *TooShort(min_words=min_words).detect(reviews),
        *CopyPaste(threshold=threshold).detect(reviews),
        *UniformScores().detect(reviews),
        *TooFast(min_seconds=min_seconds).detect(reviews),
    ]
    for flag in flags:
        assert 0.0 <= flag.score <= 1.0, flag
        assert any("а" <= ch.lower() <= "я" or ch in "ёЁ" for ch in flag.reason), flag
        assert "ivanov0" not in flag.reason
        assert "sidorova5" not in flag.reason


@PROPERTY_SETTINGS
@given(arbitrary_reviews().flatmap(lambda rs: st.tuples(st.just(rs), st.permutations(rs))))
def test_run_all_does_not_depend_on_review_order(
    sample: tuple[list[ReviewText], list[ReviewText]],
) -> None:
    """AC-6, решение 6: перестановка рецензий не меняет набор флагов."""
    original, shuffled = sample
    assert canonical(run_all(original)) == canonical(run_all(shuffled))
