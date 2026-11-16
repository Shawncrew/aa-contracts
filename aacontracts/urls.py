from django.urls import path
from django.views.i18n import JavaScriptCatalog

from . import views


app_name = "aacontracts"


urlpatterns = [
    path("", views.index, name="index"),
    path("participation/", views.participation, name="participation"),
    path("data.json", views.data, name="data"),
    path("catalog/", views.ship_catalog, name="catalog"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/jsi18n/", JavaScriptCatalog.as_view(packages=["django.contrib.admin"]), name="settings_jsi18n"),
    path("locations/", views.locations, name="locations"),
    path("locations/<int:pk>/", views.location_edit, name="location_edit"),
    path("fit/<int:pk>/history.json", views.price_history, name="price_history"),
]
