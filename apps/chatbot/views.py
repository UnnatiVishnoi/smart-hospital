"""Chat workspace: persisted conversations, scoped retrieval, grounded answers."""
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.core.permissions import visible_equipment_qs
from apps.equipment.models import Equipment
from apps.knowledge.models import ManualChunk
from apps.knowledge.rag import TOP_K, contains_injection, retrieve
from apps.knowledge.views import _visible_manuals
from .llm import (answer_with_llm, extractive_answer, is_critical_question,
                  llm_configured, safety_refusal)
from .models import ChatMessage, Conversation

SUGGESTED = [
    "What is the recommended calibration procedure?",
    "How do I troubleshoot common error codes?",
    "What are the daily inspection checks?",
    "When should filters or consumables be replaced?",
]


def _own_conversations(user):
    return Conversation.objects.filter(user=user, is_archived=False).order_by("-updated_at")


def _answer(user, question, equipment=None, history=None):
    """Full RAG turn. Returns (answer_text, sources, latency_ms, tokens, mode)."""
    started = time.perf_counter()
    refusal = safety_refusal(question)
    manuals = _visible_manuals(user)
    if equipment is not None:
        manuals = manuals.filter(Q(equipment=equipment) | Q(category=equipment.category)
                                 | Q(equipment__isnull=True, category__isnull=True))
    manual_ids = list(manuals.filter(is_indexed=True).values_list("pk", flat=True))
    if refusal:
        return refusal, [], round((time.perf_counter() - started) * 1000, 1), None, "refusal"
    chunks = list(ManualChunk.objects.filter(manual_id__in=manual_ids).select_related("manual")[:2000])
    scored = retrieve(question, chunks, top_k=TOP_K)
    titles = {m.pk: m.title for m in manuals.filter(pk__in=[c.manual_id for c, _ in scored])} if scored else {}
    if not scored:
        text = extractive_answer(question, [], {}, escalate=is_critical_question(question))
        return text, [], round((time.perf_counter() - started) * 1000, 1), None, "empty"
    sources = [{"manual_id": c.manual_id, "manual": titles.get(c.manual_id, "Manual"),
                "chunk_id": c.pk, "page_no": c.page_no, "score": s} for c, s in scored]
    passages = [{"title": titles.get(c.manual_id, "Manual"), "page_no": c.page_no,
                 "content": c.content} for c, _ in scored]
    injected = any(contains_injection(c.content) for c, _ in scored)
    if llm_configured():
        try:
            text, tokens = answer_with_llm(question, passages, history)
            if injected:
                text += ("\n\n_Note: one retrieved passage contained embedded instructions "
                         "telling me to ignore my rules. I ignored those and answered from the manual content._")
            if is_critical_question(question) and "escalat" not in text.lower():
                text += ("\n\n**Safety note:** this concerns critical equipment — escalate to "
                         "qualified biomedical personnel.")
            return text, sources, round((time.perf_counter() - started) * 1000, 1), tokens, "llm"
        except Exception:
            pass  # fall through to extractive fallback below
    text = extractive_answer(question, scored, titles, escalate=is_critical_question(question))
    return text, sources, round((time.perf_counter() - started) * 1000, 1), None, "extractive"


@login_required
def workspace(request, pk=None):
    convos = _own_conversations(request.user)
    active = get_object_or_404(convos, pk=pk) if pk else convos.first()
    equipment_qs = visible_equipment_qs(
        request.user, Equipment.objects.filter(is_active=True)).order_by("asset_tag")
    context = {
        "page_title": "AI assistant", "page_sub": "Grounded in approved equipment manuals",
        "active_nav": "assistant", "convos": convos, "active": active,
        "messages": active.messages.all() if active else [],
        "equipment_list": equipment_qs[:200],
        "suggested": SUGGESTED,
        "llm_on": llm_configured(),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "AI assistant"}],
    }
    return render(request, "chatbot/workspace.html", context)


@login_required
@require_POST
def new_conversation(request):
    eq = None
    eq_id = request.POST.get("equipment", "")
    if eq_id:
        eq = get_object_or_404(
            visible_equipment_qs(request.user, Equipment.objects.filter(is_active=True)), pk=eq_id)
    convo = Conversation.objects.create(
        user=request.user, title="New conversation", equipment=eq)
    AuditLog.objects.create(actor=request.user, action="chat", model_name="chatbot.Conversation",
                            object_id=str(convo.pk), ip_address=request.META.get("REMOTE_ADDR"))
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"id": convo.pk, "url": f"/assistant/{convo.pk}/"})
    return redirect("assistant_detail", pk=convo.pk)


@login_required
@require_POST
def ask(request, pk):
    convo = get_object_or_404(_own_conversations(request.user), pk=pk)
    question = (request.POST.get("q") or "").strip()
    if not question:
        return JsonResponse({"error": "Type a question first."}, status=400)
    if len(question) > 2000:
        return JsonResponse({"error": "Question is too long (max 2000 characters)."}, status=400)
    # Cost control: throttle answers per user per calendar hour (429 when exceeded).
    # LocMem cache = per-process; multi-worker prod needs Redis (see deployment guide).
    limit = getattr(settings, "CHAT_ASK_PER_HOUR", 30)
    bucket = timezone.now().strftime("%Y%m%d%H")
    key = f"chat-ask:{request.user.pk}:{bucket}"
    used = cache.get(key, 0)
    if used >= limit:
        return JsonResponse(
            {"error": f"Hourly question limit reached ({limit}/hour). Please try again later."},
            status=429)
    cache.set(key, used + 1, 3600)
    ChatMessage.objects.create(conversation=convo, role="user", content=question)
    history = [{"role": m.role, "content": m.content}
               for m in convo.messages.order_by("-created_at")[:6]][::-1]
    text, sources, latency, tokens, mode = _answer(request.user, question, convo.equipment, history)
    ChatMessage.objects.create(conversation=convo, role="assistant", content=text,
                               sources=sources, tokens_used=tokens, latency_ms=int(latency))
    if convo.messages.filter(role="user").count() == 1:
        convo.title = (question[:60] + "…") if len(question) > 60 else question
    convo.save(update_fields=["title", "updated_at"])
    return JsonResponse({"answer": text, "sources": sources, "latency_ms": latency, "mode": mode})


@login_required
@require_POST
def archive_conversation(request, pk):
    convo = get_object_or_404(_own_conversations(request.user), pk=pk)
    convo.is_archived = True
    convo.save(update_fields=["is_archived"])
    messages.success(request, "Conversation archived.")
    return redirect("assistant")


@login_required
@require_POST
def clear_chat(request):
    request.user.conversations.filter(is_archived=False).update(is_archived=True)
    messages.success(request, "Chat history cleared.")
    return redirect("assistant")
