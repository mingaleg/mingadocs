from django.contrib import admin
from solo.admin import SingletonModelAdmin

from .models import Document, ScanBatch, ScanPage, ScanSettings

admin.site.register(ScanSettings, SingletonModelAdmin)


class ScanPageInline(admin.TabularInline):
    model = ScanPage
    extra = 0
    fields = ("position", "scan_status", "ocr_status", "detected_arn",
              "manual_arn", "manual_continuation", "ocr_note")
    readonly_fields = fields


@admin.register(ScanBatch)
class ScanBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "created_at", "stopped_at", "finalized_at")
    list_filter = ("status",)
    inlines = [ScanPageInline]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("start_arn", "page_count", "created_at", "batch")
    search_fields = ("start_arn",)
