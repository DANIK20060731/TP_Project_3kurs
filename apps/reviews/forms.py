"""Форма рецензии, построенная по замороженной рубрике задания."""

from django import forms
from django.http import QueryDict

from .review_services import (
    MAX_CRITERION_COMMENT,
    MAX_REVIEW_COMMENT,
    ReviewCriterion,
    ReviewState,
)


class ReviewForm(forms.Form):
    version = forms.IntegerField(min_value=0, max_value=2**31 - 1, widget=forms.HiddenInput)
    comment = forms.CharField(
        label="Общий комментарий",
        required=False,
        max_length=MAX_REVIEW_COMMENT,
        widget=forms.Textarea(attrs={"rows": 5}),
    )

    def __init__(
        self,
        criteria: tuple[ReviewCriterion, ...],
        state: ReviewState,
        data: QueryDict | None = None,
    ) -> None:
        super().__init__(data=data, initial={"version": state.version, "comment": state.comment})
        self.criteria = criteria
        for criterion in criteria:
            level, comment = state.scores.get(criterion.pk, (None, ""))
            self.fields[f"level_{criterion.pk}"] = forms.TypedChoiceField(
                label=f"Уровень — {criterion.title}",
                choices=[
                    ("", "Выберите уровень"),
                    *[
                        (
                            str(option.pk),
                            f"{option.points:g} — {option.description}"
                            if option.description
                            else f"{option.points:g}",
                        )
                        for option in criterion.levels
                    ],
                ],
                coerce=int,
                empty_value=None,
                required=False,
                initial=level,
            )
            self.fields[f"criterion_comment_{criterion.pk}"] = forms.CharField(
                label=f"Комментарий — {criterion.title}",
                required=False,
                max_length=MAX_CRITERION_COMMENT,
                initial=comment,
                widget=forms.Textarea(attrs={"rows": 2}),
            )

    def selected_scores(self) -> dict[int, tuple[int | None, str]]:
        return {
            criterion.pk: (
                self.cleaned_data[f"level_{criterion.pk}"],
                self.cleaned_data[f"criterion_comment_{criterion.pk}"],
            )
            for criterion in self.criteria
        }

    @property
    def criterion_fields(self) -> list[tuple[ReviewCriterion, forms.BoundField, forms.BoundField]]:
        return [
            (criterion, self[f"level_{criterion.pk}"], self[f"criterion_comment_{criterion.pk}"])
            for criterion in self.criteria
        ]
