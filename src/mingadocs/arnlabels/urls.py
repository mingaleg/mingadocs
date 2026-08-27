from django.urls import path

from . import views

app_name = 'arnlabels'

urlpatterns = [
    path('', views.label_utility, name='label-utility'),
    path('settings/', views.print_settings, name='print-settings'),
]
