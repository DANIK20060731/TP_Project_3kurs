# apps/quality — детектор «халтурных» рецензий

Ядро (`apps/quality/detectors/`) — **чистый Python без Django**, mypy strict, покрытие ≥ 95%. Django-часть (`services.py`) достаёт рецензии из БД, вызывает детекторы и сохраняет флаги.

## Контракт (целевой)
```python
@dataclass(frozen=True)
class ReviewText:
    review_id: str
    reviewer_id: str
    comment: str
    scores: tuple[int, ...]  # оценки по критериям
    seconds_spent: int | None


@dataclass(frozen=True)
class Flag:
    review_id: str
    detector: str  # "too_short" | "copy_paste" | "uniform_scores" | "too_fast"
    reason: str  # человекочитаемо, для преподавателя
    score: float  # 0..1 — уверенность


class Detector(Protocol):
    name: str

    def detect(self, reviews: Sequence[ReviewText]) -> list[Flag]: ...
```

## Детекторы
| Детектор | Правило | Порог (настраивается в задании) |
|---|---|---|
| `too_short` | слов в комментарии < N (без стоп-слов) | N = 30 |
| `copy_paste` | Jaccard по 5-граммам слов между рецензиями ≥ T — внутри одного рецензента и между разными | T = 0.8 |
| `uniform_scores` | все оценки по критериям одинаковые при ≥ 3 критериях | — |
| `too_fast` | от открытия до отправки < S секунд | S = 60 |

## Как тестировать
- Unit-тесты на каждый детектор с граничными значениями порогов.
- **Eval-набор** `tests/fixtures/reviews_eval.json`: размеченные рецензии с ожидаемыми флагами. Тест `tests/unit/quality/test_eval.py` считает precision и recall и падает, если precision < 0.9 или recall < 0.8. При изменении детекторов размеченный набор не меняем, чтобы подогнать результат.
- Нормализация текста (регистр, пунктуация, «ё/е») — в отдельной функции с тестами.
