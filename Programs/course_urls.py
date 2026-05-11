from django.urls import path

from .catalog_course_views import (
    CourseCatalogUnitDetailView,
    CourseCatalogUnitListCreateView,
    CourseCatalogUnitRenameImpactView,
    BulkUploadCourseCatalogUnitsView,
    CourseCatalogUnitTemplateDownloadView,
)
from .course_api_views import CreateCourseUnitView, ListCourseUnitsView, UpdateCourseUnitView
from .course_api_delete_patch import DeleteCourseUnitView, PatchCourseUnitStatusView
from .semester_delete_view import DeleteSemesterForBatchView

urlpatterns = [
    path("catalog_course_units", CourseCatalogUnitListCreateView.as_view(), name="catalog_course_units"),
    path("catalog_course_units/template", CourseCatalogUnitTemplateDownloadView.as_view(), name="catalog_course_units_template"),
    path("catalog_course_units/bulk_upload", BulkUploadCourseCatalogUnitsView.as_view(), name="catalog_course_units_bulk_upload"),
    path(
        "catalog_course_units/<int:pk>/rename_impact",
        CourseCatalogUnitRenameImpactView.as_view(),
        name="catalog_course_unit_rename_impact",
    ),
    path(
        "catalog_course_units/<int:pk>",
        CourseCatalogUnitDetailView.as_view(),
        name="catalog_course_unit_detail",
    ),
    path("list_course_units", ListCourseUnitsView.as_view()),
    path("create_course_unit", CreateCourseUnitView.as_view()),
    path("update_course_unit/<int:pk>", UpdateCourseUnitView.as_view()),
    path("delete_course_unit/<int:pk>", DeleteCourseUnitView.as_view()),
    path("course_unit/<int:pk>/delete", DeleteCourseUnitView.as_view()),
    path("change_course_unit_status/<int:pk>", PatchCourseUnitStatusView.as_view()),
    path(
        "batch/<int:batch_id>/semester/<int:semester_id>/delete",
        DeleteSemesterForBatchView.as_view(),
    ),
]
