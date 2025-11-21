from django.urls import path
from accounts.views import *

app_name = 'accounts'

urlpatterns = [
    # Authentication URLs
    path("login",  ObtainTokenView.as_view()),
    path("register", RegisterView.as_view()),

    # user Urls
    path('list_users', ListUsers.as_view()),
    path('edit_user/<int:pk>', UpdateUser.as_view()),
    path('delete_user/<int:pk>', DeleteUser.as_view()),
    path('change_user_status/<int:pk>', ChangeUserStatus.as_view()),
    path('list_roles', ListRoles.as_view()),
    path('list_detailed_groups', ListDetailedRoles.as_view()),
    path('list_permissions', ListPermissions.as_view()),
    path('create_roles', CreateRoles.as_view()),
    path('edit_roles/<int:pk>', EditRoles.as_view()),
    path('delete_roles/<int:pk>', DeleteRoles.as_view()),

    # campus
    path('list_campus', ListCampus.as_view()),
    path('create_campus', CreateCampus.as_view()),
    path('edit_campus/<int:pk>', EditCampus.as_view()),
    path('delete_campus/<int:pk>', DeleteCampus.as_view()),
    
    # # Profile URLs
    path('edit_profile/<int:pk>', EditProfile.as_view()),
    path('user_profile', GetUserProfile.as_view()),
    path('get_user/<int:pk>',  getUser.as_view()),
]





