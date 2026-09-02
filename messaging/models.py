"""In-portal conversations between staff (admin / lecturer) and students."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class Conversation(models.Model):
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
    ]

    student = models.ForeignKey(
        "admissions.AdmittedStudent",
        on_delete=models.CASCADE,
        related_name="message_conversations",
    )
    subject = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations_started",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["student", "-last_message_at"]),
            models.Index(fields=["status", "-last_message_at"]),
        ]
        permissions = [
            ("use_staff_inbox", "Can message any admitted student via staff inbox"),
        ]

    def __str__(self) -> str:
        return f"Conversation #{self.pk} · student {self.student_id}"


class ConversationParticipant(models.Model):
    ROLE_STUDENT = "student"
    ROLE_STAFF = "staff"
    ROLE_CHOICES = [
        (ROLE_STUDENT, "Student"),
        (ROLE_STAFF, "Staff"),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_participations",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    last_read_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "user"],
                name="messaging_unique_conversation_participant",
            )
        ]
        indexes = [
            models.Index(fields=["user", "last_read_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in conversation {self.conversation_id}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_portal_messages",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["conversation", "id"]),
        ]

    def __str__(self) -> str:
        return f"Message #{self.pk} in conversation {self.conversation_id}"
