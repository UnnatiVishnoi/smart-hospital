from django.contrib import admin
from .models import ChatMessage, Conversation


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("role", "content", "created_at")
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "equipment", "is_archived", "updated_at")
    list_filter = ("is_archived", "created_at")
    search_fields = ("title", "user__username")
    inlines = [ChatMessageInline]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "created_at", "tokens_used")
    list_filter = ("role", "created_at")
    search_fields = ("content",)
