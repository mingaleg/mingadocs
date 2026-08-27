from __future__ import annotations

from django import forms

from arnlabels.arn import Arn
from arnlabels.models import PrintSettings

from .models import ScanSettings


class ScanSettingsForm(forms.ModelForm):
    class Meta:
        model = ScanSettings
        fields = ["sane_device", "resolution_dpi", "mode", "ocr_timeout_seconds"]

    def __init__(self, *args, devices=None, **kwargs):
        super().__init__(*args, **kwargs)
        if devices:
            current = self.instance.sane_device
            choices = [("", "--- SANE default ---")] + [(d, d) for d in devices]
            if current and current not in devices:
                choices.append((current, f"{current} (not detected)"))
            self.fields["sane_device"] = forms.ChoiceField(
                required=False, choices=choices, label="Scanner",
            )


class PageArnForm(forms.Form):
    MODE_ARN = "arn"
    MODE_CONTINUATION = "continuation"
    MODE_CLEAR = "clear"
    MODE_CHOICES = [
        (MODE_ARN, "Set ARN"),
        (MODE_CONTINUATION, "Mark as continuation"),
        (MODE_CLEAR, "Clear override"),
    ]

    mode = forms.ChoiceField(choices=MODE_CHOICES)
    # The prefix is global and permanent; it is shown pre-filled and read-only
    # in the UI, and whatever is posted is ignored in favour of the configured
    # value. The body is entered as its three parts: year (pre-filled with the
    # current year), volume and index.
    arn_prefix = forms.CharField(required=False)
    arn_year = forms.CharField(required=False)
    arn_volume = forms.CharField(required=False)
    arn_index = forms.CharField(required=False)

    def _part(self, cleaned, field, label):
        raw = (cleaned.get(field) or "").strip()
        try:
            return int(raw)
        except ValueError:
            self.add_error(field, f"{label} must be a number")
            return None

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("mode") == self.MODE_ARN:
            prefix = PrintSettings.get_solo().arn_prefix
            year = self._part(cleaned, "arn_year", "Year")
            volume = self._part(cleaned, "arn_volume", "Volume")
            index = self._part(cleaned, "arn_index", "Index")
            if None not in (year, volume, index):
                try:
                    arn = Arn.volume_start(prefix, year, volume, index)
                except ValueError as exc:
                    self.add_error("arn_index", str(exc))
                else:
                    cleaned["arn"] = arn.barcode_value()
        return cleaned
