from django.contrib import admin
from solo.admin import SingletonModelAdmin

from .models import PrintSettings, VolumeAllocation

admin.site.register(PrintSettings, SingletonModelAdmin)


@admin.register(VolumeAllocation)
class VolumeAllocationAdmin(admin.ModelAdmin):
    list_display = ('year', 'volume', 'max_index', 'created_at')
    list_filter = ('year',)
