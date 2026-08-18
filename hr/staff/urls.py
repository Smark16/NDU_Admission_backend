from django.urls import path
from . import views
from . import id_card_views

app_name = 'staff'

urlpatterns = [
    path('profiles/', views.StaffProfileListView.as_view(), name='staff_profile_list'),
    path('profiles/<int:staff_id>/', views.StaffProfileDetailView.as_view(), name='staff_profile_detail'), 
    path('profiles/create/', views.CreateStaffProfileView.as_view(), name='staff_profile_create'),
    path('profiles/<int:pk>/update/', views.UpdateStaffProfileView.as_view(), name='staff_profile_update'),
    path('profiles/<int:pk>/delete/', views.DeleteStaffProfileView.as_view(), name='staff_profile_delete'),
    path('staff_profile/<int:user_id>/', views.MiniStaffProfile.as_view()),
    path('me/', views.CurrentStaffProfileView.as_view(), name='staff_profile_me'),
    path('contracts/', views.StaffContractListView.as_view(), name='staff_contract_list'),
    path('contracts/create/', views.StaffContractCreateView.as_view(), name='staff_contract_create'),

    # department URLs
    path('departments/', views.DepartmentListView.as_view(), name='department_list'),
    path('list_depts/', views.ListDepartments.as_view()),
    path('departments/create/', views.CreateDepartmentView.as_view(), name='department_create'),
    path('departments/<int:pk>/update/', views.UpdateDepartmentView.as_view(), name='department_update'),
    path('departments/<int:pk>/delete/', views.DeleteDepartmentView.as_view(), name='department_delete'), 
    path('department_units/', views.DepartmentUnits.as_view()),
    path('department_staff/', views.DepartmentStaff.as_view()),

    # unit types urls
    path('unit_types/', views.ListUnits.as_view(), name='unit_type_list'),
    path('unit_types/create/', views.CreateUnit.as_view(), name='unit_type_create'),
    path('unit_types/<int:pk>/update/', views.UpdateUnit.as_view(), name='unit_type_update'),
    path('unit_types/<int:pk>/delete/', views.DeleteUnit.as_view(), name='unit_type_delete'),

    # level types urls
    path('level_types/', views.ListLevels.as_view()),
    path('level_types/create/', views.CreateLevels.as_view()),
    path('level_types/<int:pk>/update/', views.UpdateLevels.as_view()),
    path('level_types/<int:pk>/delete/', views.DeleteLevel.as_view()),

    # pay scales (Ugandan U/P grades)
    path('pay_scales/', views.ListPayScales.as_view()),
    path('pay_scales/create/', views.CreatePayScale.as_view()),
    path('pay_scales/<int:pk>/update/', views.UpdatePayScale.as_view()),
    path('pay_scales/<int:pk>/delete/', views.DeletePayScale.as_view()),

    # team urls
    path('teams/', views.ListTeams.as_view(), name='team_list'),
    path('teams/create/', views.CreateTeam.as_view(), name='team_create'),  
    path('teams/<int:pk>/update/', views.UpdateTeam.as_view(), name='team_update'),
    path('teams/<int:pk>/delete/', views.DeleteTeam.as_view(), name='team_delete'),

    # staff list
     path('supervised/staff/', views.SupervisorStaffListView.as_view(), name='supervisor-staff'),
     path('export/template/', views.ExportSampleCSV.as_view(), name='staff-upload-template'),
     path('upload_template/', views.HandleBulkStaffUpload.as_view(), name='staff-bulk-upload'),

    path('id_cards/eligible', id_card_views.StaffIdCardEligibleListView.as_view(), name='staff_id_cards_eligible'),
    path('id_cards/filter-options', id_card_views.StaffIdCardFilterOptionsView.as_view(), name='staff_id_cards_filter_options'),
    path(
        'id_cards/profile/<int:staff_id>/passport_photo',
        id_card_views.StaffIdCardPassportPhotoView.as_view(),
        name='staff_id_cards_passport_photo',
    ),
    path('id_cards/generate', id_card_views.StaffIdCardGenerateView.as_view(), name='staff_id_cards_generate'),
    path('id_cards/<int:card_id>/preview-data', id_card_views.StaffIdCardPreviewDataView.as_view(), name='staff_id_cards_preview'),
    path('id_cards/<int:card_id>/print.pdf', id_card_views.StaffIdCardPrintPdfView.as_view(), name='staff_id_cards_print_pdf'),
    path('id_cards/<int:card_id>/revoke', id_card_views.StaffIdCardRevokeView.as_view(), name='staff_id_cards_revoke'),
    path('id_cards/<int:card_id>/reissue', id_card_views.StaffIdCardReissueView.as_view(), name='staff_id_cards_reissue'),
    path('id_cards', id_card_views.StaffIdCardListView.as_view(), name='staff_id_cards_list'),
]

