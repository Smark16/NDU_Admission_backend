from django.contrib import admin

from messaging.models import Conversation, ConversationParticipant, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("sender", "body", "created_at")
    can_delete = False


class ParticipantInline(admin.TabularInline):
    model = ConversationParticipant
    extra = 0


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "subject", "status", "last_message_at", "created_by")
    list_filter = ("status",)
    search_fields = ("subject", "student__reg_no", "student__student_id")
    inlines = [ParticipantInline, MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "created_at")
    search_fields = ("body", "sender__username", "sender__email")
