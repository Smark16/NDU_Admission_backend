from django.urls import path

from messaging import views

urlpatterns = [
    path("conversations/", views.ConversationListCreateView.as_view(), name="messaging-conversations"),
    path(
        "conversations/<int:pk>/",
        views.ConversationDetailView.as_view(),
        name="messaging-conversation-detail",
    ),
    path(
        "conversations/<int:pk>/messages/",
        views.ConversationMessagesView.as_view(),
        name="messaging-messages",
    ),
    path(
        "conversations/<int:pk>/read/",
        views.ConversationReadView.as_view(),
        name="messaging-read",
    ),
    path(
        "conversations/<int:pk>/close/",
        views.ConversationCloseView.as_view(),
        name="messaging-close",
    ),
    path("unread_count/", views.UnreadCountView.as_view(), name="messaging-unread"),
    path("students/search/", views.StudentSearchView.as_view(), name="messaging-student-search"),
    path("my_lecturers/", views.MyLecturersView.as_view(), name="messaging-my-lecturers"),
    path("faculty_contacts/", views.FacultyContactsView.as_view(), name="messaging-faculty-contacts"),
]
