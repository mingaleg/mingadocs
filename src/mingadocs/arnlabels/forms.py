"""Forms for the label utility page and settings page."""
# ModelForm is generic in django-stubs, subscriptable at runtime via
# django_stubs_ext.monkeypatch() (see settings).
# pylint: disable=unsubscriptable-object
from __future__ import annotations

from django import forms

from .enums import OutputMode, PageType
from .models import PrintSettings


class PrintSettingsForm(forms.ModelForm[PrintSettings]):
    class Meta:
        model = PrintSettings
        fields = ["arn_prefix", "cups_printer", "print_directly_by_default"]

    def __init__(
        self, *args: object, printers: list[str] | None = None, **kwargs: object
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        if printers:
            self.fields["cups_printer"] = forms.ChoiceField(
                required=False,
                choices=[("", "--- download only ---")]
                + [(p, p) for p in printers],
                initial=self.instance.cups_printer,
            )


class LabelBatchForm(forms.Form):
    PAGE_CHOICES = [
        (PageType.VOLUME.value, "Volume page (new documents)"),
        (PageType.CONTINUATION.value, "Continuation page"),
    ]
    OUTPUT_CHOICES = [
        (OutputMode.PRINT.value, "Send to printer"),
        (OutputMode.PDF.value, "Render PDF"),
    ]

    # Driven by the tab strip in the template.
    page_type = forms.ChoiceField(
        choices=PAGE_CHOICES, widget=forms.HiddenInput,
        initial=PageType.VOLUME.value,
    )
    year = forms.IntegerField(min_value=1000, max_value=9999, required=False)
    volume = forms.IntegerField(min_value=0, max_value=99, required=False)
    # Set by which submit button was pressed (name="output").
    output = forms.ChoiceField(
        choices=OUTPUT_CHOICES, widget=forms.HiddenInput, required=False
    )

    def clean(self) -> dict[str, object]:
        cleaned: dict[str, object] = super().clean() or {}
        if cleaned.get("page_type") == PageType.VOLUME:
            for field in ("year", "volume"):
                if cleaned.get(field) is None:
                    self.add_error(field, "Required for a volume page.")
        return cleaned
