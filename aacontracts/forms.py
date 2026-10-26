from django import forms

from .models import GlobalConfig, Location


class GlobalConfigForm(forms.ModelForm):
    class Meta:
        model = GlobalConfig
        fields = [
            "price_markup_percent",
            "price_basis",
            "discord_enabled",
            "discord_channel_id",
            "ping_group",
            "discord_update_seconds",
        ]
        widgets = {
            "price_markup_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.1"}),
            "price_basis": forms.Select(attrs={"class": "form-select"}),
            "discord_channel_id": forms.NumberInput(attrs={"class": "form-control"}),
            "ping_group": forms.Select(attrs={"class": "form-select"}),
            "discord_update_seconds": forms.NumberInput(attrs={"class": "form-control"}),
        }


class LocationForm(forms.ModelForm):
    """Location form whose ``location_id`` is a searchable dropdown of the
    stations/structures where alliance contracts exist (so users don't have to
    look up raw ids). Pass ``candidates`` (from ``queries.candidate_locations``).
    """

    class Meta:
        model = Location
        # system_name is derived from the chosen station, not entered.
        fields = ["name", "location_id", "enabled", "order"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "order": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, candidates=None, **kwargs):
        super().__init__(*args, **kwargs)
        candidates = candidates or []
        choices = [("", "— pick a station / structure —")]
        seen = set()
        for c in candidates:
            choices.append((str(c["location_id"]), c["name"]))
            seen.add(c["location_id"])
        # Keep the current value selectable even if it has no live contracts.
        current = self.instance.location_id if self.instance and self.instance.pk else None
        if current and current not in seen:
            label = self.instance.name or f"Location {current}"
            choices.insert(1, (str(current), f"{label} (current)"))
        self.fields["location_id"] = forms.TypedChoiceField(
            choices=choices,
            coerce=int,
            empty_value=None,
            widget=forms.Select(attrs={"class": "form-select"}),
            label="Station / structure",
            help_text="Pick where contracts are placed. Type to search the list.",
        )
