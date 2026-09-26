"""Seed a sample ventilator maintenance manual (PyMuPDF-generated, ORM only).

Run: python manage.py seed_demo_manual — idempotent by file hash.
Gives reviewers real end-to-end RAG content without hunting for PDFs.
"""
import hashlib
from pathlib import Path

import pymupdf
from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.equipment.models import Category
from apps.knowledge.models import EquipmentManual
from apps.knowledge.rag import index_manual

PAGES = [
    ("CALIBRATION PROCEDURE",
     "Calibration Procedure\n\nCalibrate the ventilator flow sensor every 90 days using a calibrated test lung. "
     "Connect the test lung to the patient circuit, set the device to calibration mode, and follow the on-screen steps. "
     "Acceptance criterion: flow accuracy within plus or minus 5 percent. Record the result in the service log. "
     "If calibration fails twice, escalate to a qualified biomedical engineer."),
    ("ERROR CODE TROUBLESHOOTING",
     "Error Code Troubleshooting\n\nError E4 indicates a flow sensor fault. Power-cycle the device, inspect the "
     "sensor for moisture, and replace the bacterial filter. Error E7 indicates low supply pressure; check the oxygen "
     "hose connection and wall outlet pressure. Never silence alarms during troubleshooting. "
     "If either error persists after two attempts, escalate to a qualified biomedical engineer."),
    ("DAILY INSPECTION CHECKS",
     "Daily Inspection Checks\n\nBefore clinical use, verify the power cord, backup battery charge above 80 percent, "
     "circuit integrity, and humidifier water level. Run the automated self-test and confirm all alarms sound. "
     "Replace the bacterial filter every 30 days or sooner if visibly soiled. Document checks in the ward log."),
]


class Command(BaseCommand):
    help = "Generate + index a sample ventilator manual (idempotent)."

    def handle(self, *args, **opts):
        media = Path(settings.MEDIA_ROOT) / "manuals"
        media.mkdir(parents=True, exist_ok=True)
        pdf_path = media / "demo-ventilator-guide.pdf"
        doc = pymupdf.open()
        for heading, body in PAGES:
            page = doc.new_page()
            page.insert_text((72, 100), heading, fontsize=16)
            page.insert_text((72, 140), body, fontsize=11)
        doc.save(pdf_path)
        doc.close()
        digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        with transaction.atomic():
            if EquipmentManual.objects.filter(file_hash=digest).exists():
                self.stdout.write("Demo manual already present — skipping.")
                return
            cat = Category.objects.filter(name__icontains="ventilator").first()
            manual = EquipmentManual(title="Demo Ventilator Maintenance Guide", category=cat,
                                     manufacturer="DemoMed", model="VX-100", version="1.0",
                                     file_hash=digest)
            with pdf_path.open("rb") as fh:
                manual.file.save("demo-ventilator-guide.pdf", File(fh), save=False)
            manual.save()
            n = index_manual(manual)
        self.stdout.write(self.style.SUCCESS(
            f"Demo manual indexed: {n} passages from {manual.page_count} pages. Ask about calibration or error E4."))
