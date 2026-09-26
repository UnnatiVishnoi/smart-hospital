"""Phase 11 — AI cost control: per-user hourly ask throttle (429, nothing persisted)."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from apps.chatbot.models import ChatMessage, Conversation

PW = "T3stPass!!"
U = get_user_model()


@override_settings(CHAT_ASK_PER_HOUR=2)
class ThrottleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        o, _ = U.objects.get_or_create(username="t_user", defaults={"email": "t@t.local", "role": "staff"})
        o.email = "t@t.local"
        o.role = "staff"
        o.is_active = True
        o.set_password(PW)
        o.save()
        cls.user = o
        cls.convo = Conversation.objects.create(user=o, title="Throttle check")

    def test_two_ok_third_rejected_without_persisting(self):
        c = Client()
        c.login(username="t_user", password=PW)
        self.assertEqual(c.post(f"/assistant/{self.convo.pk}/ask/",
                               {"q": "First maintenance question here?"}).status_code, 200)
        self.assertEqual(c.post(f"/assistant/{self.convo.pk}/ask/",
                               {"q": "Second maintenance question here?"}).status_code, 200)
        r = c.post(f"/assistant/{self.convo.pk}/ask/", {"q": "Third question blocked?"})
        self.assertEqual(r.status_code, 429)
        self.assertIn("limit", r.json()["error"])
        self.assertEqual(ChatMessage.objects.filter(conversation=self.convo, role="user").count(), 2)
