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
    # value. Only the 9-digit body is really entered by hand.
    arn_prefix = forms.CharField(required=False)
    arn_body = forms.CharField(required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("mode") == self.MODE_ARN:
            prefix = PrintSettings.get_solo().arn_prefix
            body = (cleaned.get("arn_body") or "").strip().replace(" ", "")
            raw = f"{prefix}{body}"
            try:
                Arn.parse(raw, prefix)
            except ValueError as exc:
                self.add_error("arn_body", str(exc))
            else:
                cleaned["arn"] = raw
        return cleaned
