from django.urls import path

from . import views


app_name = "aacontracts"


urlpatterns = [
    path("", views.index, name="index"),
    path("data.json", views.data, name="data"),
]
