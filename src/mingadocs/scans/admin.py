# django-stubs types ModelAdmin/TabularInline as generic; they are made
# subscriptable at runtime by django_stubs_ext.monkeypatch() (see settings).
# pylint: disable=unsubscriptable-object
from django.contrib import admin
from solo.admin import SingletonModelAdmin

from .models import Document, ScanBatch, ScanPage, ScanSettings

admin.site.register(ScanSettings, SingletonModelAdmin)


class ScanPageInline(admin.TabularInline[ScanPage, ScanBatch]):
    model = ScanPage
    extra = 0
    fields = ("position", "scan_status", "ocr_status", "detected_arn",
              "manual_arn", "manual_continuation", "ocr_note")
    readonly_fields = fields


@admin.register(ScanBatch)
class ScanBatchAdmin(admin.ModelAdmin[ScanBatch]):
    list_display = ("id", "status", "created_at", "stopped_at", "finalized_at")
    list_filter = ("status",)
    inlines = [ScanPageInline]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin[Document]):
    list_display = ("start_arn", "page_count", "created_at", "batch")
    search_fields = ("start_arn",)
