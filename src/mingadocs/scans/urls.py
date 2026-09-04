from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "scans"

urlpatterns = [
    path("", views.batch_list, name="batch-list"),
    path("new/", views.new_batch, name="new-batch"),
    path("documents/", views.document_list, name="document-list"),
    path("documents/thumbnails/regenerate/", views.thumbnails_regenerate,
         name="thumbnails-regenerate"),
    path("documents/thumbnails/regenerate/status/",
         views.thumbnails_regenerate_status, name="thumbnails-regenerate-status"),
    path("documents/thumbnails/<int:page>/", views.document_thumb_urls,
         name="document-thumb-urls"),
    # Settings moved to their own module at /settings/; keep old links working.
    path("settings/", RedirectView.as_view(url="/settings/", query_string=True)),
    path("<int:batch_id>/", views.batch_console, name="console"),
    path("<int:batch_id>/review/", views.batch_review, name="review"),
    path("<int:batch_id>/status/", views.batch_status, name="status"),
    path("<int:batch_id>/scan/", views.scan_page, name="scan"),
    path("<int:batch_id>/stop/", views.stop_batch, name="stop"),
    path("<int:batch_id>/discard/", views.discard_batch, name="discard"),
    path("<int:batch_id>/reorder/", views.reorder, name="reorder"),
    path("<int:batch_id>/finalize/", views.finalize, name="finalize"),
    path("<int:batch_id>/pages/<int:page_id>/", views.page_detail, name="page"),
    path("<int:batch_id>/pages/<int:page_id>/arn/", views.page_arn, name="page-arn"),
    path("<int:batch_id>/pages/<int:page_id>/remove/", views.page_remove,
         name="page-remove"),
]
