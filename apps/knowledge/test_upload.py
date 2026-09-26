"""Phase 11 — manual upload validation: type, size, duplicates (manager-only)."""
import hashlib

import pymupdf
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from apps.knowledge.models import EquipmentManual

PW = "T3stPass!!"
U = get_user_model()


def mkuser(u, role):
    o, _ = U.objects.get_or_create(username=u, defaults={"email": f"{u}@t.local", "role": role})
    o.email = f"{u}@t.local"
    o.role = role
    o.is_active = True
    o.set_password(PW)
    o.save()
    return o


def tiny_pdf():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Pump maintenance guide. Check seals and tubing daily. "
                                "Replace tubing every 7 days. Log all work.", fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


class ManualUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mgr = mkuser("k_mgr", "manager")
        cls.staff = mkuser("k_staff", "staff")

    def _login(self, u):
        c = Client()
        c.login(username=u, password=PW)
        return c

    def test_staff_cannot_upload(self):
        pdf = tiny_pdf()
        r = self._login("k_staff").post("/manuals/upload/", {
            "title": "Nope", "file": SimpleUploadedFile("x.pdf", pdf, "application/pdf")})
        self.assertEqual(r.status_code, 403)

    def test_non_pdf_rejected(self):
        r = self._login("k_mgr").post("/manuals/upload/", {
            "title": "Fake", "file": SimpleUploadedFile("f.pdf", b"not a pdf at all", "application/pdf")})
        self.assertEqual(r.status_code, 200)
        self.assertIn("not a valid PDF", r.content.decode())

    def test_oversize_rejected(self):
        big = b"%PDF-" + b"0" * (21 * 1024 * 1024)
        r = self._login("k_mgr").post("/manuals/upload/", {
            "title": "Big", "file": SimpleUploadedFile("big.pdf", big, "application/pdf")})
        self.assertEqual(r.status_code, 200)
        self.assertIn("under 20 MB", r.content.decode())

    def test_valid_upload_indexed_and_duplicate_blocked(self):
        pdf = tiny_pdf()
        c = self._login("k_mgr")
        r = c.post("/manuals/upload/", {
            "title": "Pump Guide", "manufacturer": "DemoMed",
            "file": SimpleUploadedFile("pump.pdf", pdf, "application/pdf")})
        self.assertEqual(r.status_code, 302)
        manual = EquipmentManual.objects.get(title="Pump Guide")
        self.assertTrue(manual.is_indexed)
        self.assertGreater(manual.chunks.count(), 0)
        self.assertEqual(manual.file_hash, hashlib.sha256(pdf).hexdigest())
        dup = c.post("/manuals/upload/", {
            "title": "Pump Guide Copy",
            "file": SimpleUploadedFile("pump2.pdf", pdf, "application/pdf")})
        self.assertEqual(dup.status_code, 200)
        self.assertIn("already uploaded", dup.content.decode())
