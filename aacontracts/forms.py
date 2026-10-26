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
    class Meta:
        model = Location
        fields = ["name", "location_id", "system_name", "enabled", "order"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "location_id": forms.NumberInput(attrs={"class": "form-control"}),
            "system_name": forms.TextInput(attrs={"class": "form-control"}),
            "order": forms.NumberInput(attrs={"class": "form-control"}),
        }
