from django.urls import path

from . import views

app_name = "arnlabels"

urlpatterns = [
    path("", views.index, name="index"),
    path("labels/", views.label_utility, name="label-utility"),
    path("labels/settings/", views.print_settings, name="print-settings"),
]
