"""Forms for the label utility page and settings page."""
from __future__ import annotations

from typing import Any

from django import forms

from .models import PrintSettings
from .services import PAGE_CONTINUATION, PAGE_VOLUME


class PrintSettingsForm(forms.ModelForm):
    class Meta:
        model = PrintSettings
        fields = ["arn_prefix", "cups_printer", "print_directly_by_default"]

    def __init__(
        self, *args: Any, printers: list[str] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        if printers:
            self.fields["cups_printer"] = forms.ChoiceField(
                required=False,
                choices=[("", "--- download only ---")]
                + [(p, p) for p in printers],
                initial=self.instance.cups_printer,
            )


class LabelBatchForm(forms.Form):
    PAGE_CHOICES = [
        (PAGE_VOLUME, "Volume page (new documents)"),
        (PAGE_CONTINUATION, "Continuation page"),
    ]
    OUTPUT_CHOICES = [
        ("print", "Send to printer"),
        ("pdf", "Render PDF"),
    ]

    # Driven by the tab strip in the template.
    page_type = forms.ChoiceField(
        choices=PAGE_CHOICES, widget=forms.HiddenInput, initial=PAGE_VOLUME
    )
    year = forms.IntegerField(min_value=1000, max_value=9999, required=False)
    volume = forms.IntegerField(min_value=0, max_value=99, required=False)
    # Set by which submit button was pressed (name="output").
    output = forms.ChoiceField(
        choices=OUTPUT_CHOICES, widget=forms.HiddenInput, required=False
    )

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        if cleaned.get("page_type") == PAGE_VOLUME:
            for field in ("year", "volume"):
                if cleaned.get(field) is None:
                    self.add_error(field, "Required for a volume page.")
        return cleaned
