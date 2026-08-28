# django-stubs types ModelAdmin/ModelForm as generic; they are made
# subscriptable at runtime by django_stubs_ext.monkeypatch() (see settings).
# pylint: disable=unsubscriptable-object
from django.contrib import admin
from solo.admin import SingletonModelAdmin

from .models import PrintSettings, VolumeAllocation

admin.site.register(PrintSettings, SingletonModelAdmin)


@admin.register(VolumeAllocation)
class VolumeAllocationAdmin(admin.ModelAdmin[VolumeAllocation]):
    list_display = ('year', 'volume', 'max_index', 'created_at')
    list_filter = ('year',)
