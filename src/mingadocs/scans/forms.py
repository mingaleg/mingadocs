from __future__ import annotations

# ModelForm is generic in django-stubs, subscriptable at runtime via
# django_stubs_ext.monkeypatch() (see settings).
# pylint: disable=unsubscriptable-object
from django import forms

from arnlabels.arn import Arn
from arnlabels.models import PrintSettings

from .enums import ArnMode
from .models import ScanSettings


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected an int, got {value!r}")
    return value


class ScanSettingsForm(forms.ModelForm[ScanSettings]):
    class Meta:
        model = ScanSettings
        fields = ["sane_device", "resolution_dpi", "mode", "ocr_timeout_seconds"]

    def __init__(
        self, *args: object, devices: list[str] | None = None, **kwargs: object
    ) -> None:
        # Django's BaseForm.__init__ has a long explicit signature; forward
        # opaquely and let it validate the shape at runtime.
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        if devices:
            current = self.instance.sane_device
            choices = [("", "--- SANE default ---")] + [(d, d) for d in devices]
            if current and current not in devices:
                choices.append((current, f"{current} (not detected)"))
            self.fields["sane_device"] = forms.ChoiceField(
                required=False, choices=choices, label="Scanner",
            )


class PageArnForm(forms.Form):
    """The manual-override form on the page-detail page.

    ``mode`` selects the edit; for :attr:`ArnMode.SET` the body is entered as
    three integer parts (the prefix is global and read-only, whatever is
    posted for it is ignored). :meth:`arn_mode` / :meth:`arn_value` expose the
    validated result as typed data.
    """

    _PARTS = ("year", "volume", "index")

    mode = forms.ChoiceField(choices=[
        (ArnMode.SET.value, "Set ARN"),
        (ArnMode.CONTINUATION.value, "Mark as continuation"),
        (ArnMode.CLEAR.value, "Clear override"),
    ])
    arn_prefix = forms.CharField(required=False)
    arn_year = forms.IntegerField(required=False)
    arn_volume = forms.IntegerField(required=False)
    arn_index = forms.IntegerField(required=False)

    _barcode_value: str = ""

    def clean(self) -> dict[str, object]:
        cleaned: dict[str, object] = super().clean() or {}
        self._barcode_value = ""
        if str(cleaned.get("mode")) != ArnMode.SET:
            return cleaned

        raw = {name: cleaned.get(f"arn_{name}") for name in self._PARTS}
        for name, value in raw.items():
            if value is None:
                self.add_error(f"arn_{name}", "Required to set an ARN.")
        if self.errors:
            return cleaned

        prefix = PrintSettings.get_solo().arn_prefix
        try:
            arn = Arn.volume_start(
                prefix,
                _as_int(raw["year"]),
                _as_int(raw["volume"]),
                _as_int(raw["index"]),
            )
        except ValueError as exc:
            self.add_error("arn_index", str(exc))
        else:
            self._barcode_value = arn.barcode_value()
        return cleaned

    def arn_mode(self) -> ArnMode:
        return ArnMode(str(self.cleaned_data["mode"]))

    def arn_value(self) -> str:
        return self._barcode_value
