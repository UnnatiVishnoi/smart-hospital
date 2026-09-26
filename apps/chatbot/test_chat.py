"""Phase 8 tests — run: python manage.py test apps.chatbot apps.knowledge (MySQL test DB)."""
import pymupdf
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from apps.chatbot.llm import safety_refusal
from apps.chatbot.models import ChatMessage, Conversation
from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.knowledge.models import EquipmentManual, ManualChunk
from apps.knowledge.rag import chunk_pages, extract_pages, retrieve

PW = "T3stPass!!"


def mkuser(u, role, dept=None):
    U = get_user_model()
    o, _ = U.objects.get_or_create(username=u, defaults={"email": f"{u}@t.local", "role": role})
    o.email = f"{u}@t.local"
    o.role = role
    o.is_active = True
    o.department = dept
    o.set_password(PW)
    o.save()
    return o


def make_pdf_bytes(texts):
    doc = pymupdf.open()
    for t in texts:
        page = doc.new_page()
        page.insert_text((72, 100), t, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


class RagUnitTests(TestCase):
    def test_extract_and_chunk(self):
        pdf = make_pdf_bytes(["Calibration Procedure\n" + "Flow sensor check. " * 120,
                              "Error Codes\n" + "Error E4 means sensor fault. " * 120])
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(pdf)
            path = fh.name
        try:
            pages = extract_pages(path)
            self.assertEqual(len(pages), 2)
            chunks = chunk_pages(pages, size=400, overlap=50)
            self.assertGreaterEqual(len(chunks), 2)
            self.assertEqual(chunks[0]["page_no"], 1)
        finally:
            os.unlink(path)

    def test_retrieve_ranks_relevant_chunk(self):
        class C:
            def __init__(self, content):
                self.content = content
        chunks = [C("Daily inspection checks for the ward monitor power cord."),
                  C("Calibration procedure for the flow sensor every 90 days."),
                  C("Warranty terms and vendor contact information.")]
        top = retrieve("how to calibrate the flow sensor", chunks, top_k=1)
        self.assertEqual(len(top), 1)
        self.assertIn("Calibration", top[0][0].content)

    def test_safety_refusals(self):
        self.assertIsNotNone(safety_refusal("How do I bypass the ventilator alarm?"))
        self.assertIsNotNone(safety_refusal("Diagnose this patient ECG reading"))
        self.assertIsNone(safety_refusal("How do I calibrate the flow sensor?"))


class ChatFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name="AI ICU", code="AICU", location="F1")
        cls.cat = Category.objects.create(name="AI Vent")
        cls.eq = Equipment.objects.create(
            asset_tag="AI-AICU-001", name="AI Vent", category=cls.cat, department=cls.dept,
            manufacturer="DemoMed", model_no="VX", serial_no="SN-AI-1",
            purchase_date="2024-01-05")
        cls.mgr = mkuser("ai_mgr", "manager")
        cls.staff = mkuser("ai_staff", "staff", cls.dept)
        cls.tech = mkuser("ai_tech", "technician")
        pdf = make_pdf_bytes(["Calibration Procedure Flow sensor calibration every 90 days with test lung. " * 30,
                              "Error E4 flow sensor fault power cycle replace filter escalate engineer. " * 30])
        import hashlib
        manual = EquipmentManual.objects.create(
            title="AI Vent Guide", category=cls.cat, file_hash=hashlib.sha256(pdf).hexdigest())
        manual.file.save("ai-test.pdf", SimpleUploadedFile("ai-test.pdf", pdf, "application/pdf"))
        from apps.knowledge.rag import index_manual
        index_manual(manual)
        cls.manual = manual

    def _login(self, u):
        c = Client()
        c.login(username=u, password=PW)
        return c

    def test_end_to_end_grounded_answer_with_citation(self):
        c = self._login("ai_staff")
        r = c.post("/assistant/new/", {"equipment": str(self.eq.pk)})
        convo = Conversation.objects.get(user=self.staff)
        self.assertEqual(r.status_code, 302)
        r = c.post(f"/assistant/{convo.pk}/ask/", {"q": "How do I calibrate the flow sensor?"})
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertIn("calibration", payload["answer"].lower())
        self.assertTrue(payload["sources"])
        self.assertEqual(payload["sources"][0]["manual"], "AI Vent Guide")
        self.assertEqual(ChatMessage.objects.filter(conversation=convo).count(), 2)

    def test_empty_corpus_says_so(self):
        ManualChunk.objects.all().delete()
        c = self._login("ai_staff")
        convo = Conversation.objects.create(user=self.staff)
        r = c.post(f"/assistant/{convo.pk}/ask/", {"q": "How do I calibrate the flow sensor?"})
        self.assertIn("couldn't find", r.json()["answer"])

    def test_refusal_for_bypass(self):
        c = self._login("ai_staff")
        convo = Conversation.objects.create(user=self.staff)
        r = c.post(f"/assistant/{convo.pk}/ask/", {"q": "How do I bypass the ventilator alarm?"})
        self.assertIn("can't help bypass", r.json()["answer"])
        self.assertEqual(r.json()["sources"], [])

    def test_permissions(self):
        # staff cannot upload; tech cannot upload; anon redirected
        self.assertEqual(self._login("ai_staff").get("/manuals/upload/").status_code, 403)
        self.assertEqual(self._login("ai_tech").get("/manuals/upload/").status_code, 403)
        self.assertEqual(Client().get("/assistant/").status_code, 302)
        # staff cannot read another user's conversation
        other = Conversation.objects.create(user=self.mgr)
        self.assertEqual(self._login("ai_staff").get(f"/assistant/{other.pk}/").status_code, 404)
        # duplicate PDF blocked
        c = self._login("ai_mgr")
        manual = EquipmentManual.objects.get(title="AI Vent Guide")
        dup = SimpleUploadedFile("dup.pdf", open(manual.file.path, "rb").read(), "application/pdf")
        r = c.post("/manuals/upload/", {"title": "Dup", "file": dup})
        self.assertEqual(r.status_code, 200)  # form error, not redirect
        self.assertIn("already uploaded", r.content.decode())
