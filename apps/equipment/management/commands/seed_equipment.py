"""Seed realistic hospital equipment (idempotent, ORM only). Run: python manage.py seed_equipment."""
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.inventory.models import Vendor

DEPTS = [
    ("Intensive Care Unit", "ICU", "Floor 2"),
    ("Emergency", "ER", "Ground floor"),
    ("Radiology", "RAD", "Floor 1"),
    ("General Ward", "WARD", "Floor 3"),
    ("Operation Theatre", "OT", "Floor 2"),
    ("Cardiology", "CARD", "Floor 4"),
    ("Laboratory", "LAB", "Floor 1"),
]

CATS = ["Ventilator", "Patient Monitor", "Infusion Pump", "Defibrillator", "X-Ray", "ECG", "Ultrasound", "Autoclave"]

VENDORS = [
    ("Philips Healthcare", "Imaging & monitoring"),
    ("GE HealthCare", "Imaging & diagnostics"),
    ("Siemens Healthineers", "Imaging"),
    ("Medtronic", "Critical care"),
    ("CityMed Services", "Local AMC partner"),
]

# (name, category, dept, manufacturer, model, serial, age_days, warranty_years, criticality, status, location)
ITEMS = [
    ("ICU Ventilator — Bed 1", "Ventilator", "ICU", "Philips", "Trilogy Evo", "SN-VEN-1001", 900, 3, "critical", "operational", "ICU · Bed 1"),
    ("ICU Ventilator — Bed 4", "Ventilator", "ICU", "Medtronic", "PB980", "SN-VEN-1004", 1200, 3, "critical", "breakdown", "ICU · Bed 4"),
    ("Transport Ventilator", "Ventilator", "ER", "Philips", "Trilogy 202", "SN-VEN-2001", 500, 2, "high", "operational", "ER bay"),
    ("Bedside Monitor — Bed 2", "Patient Monitor", "ICU", "Philips", "IntelliVue MX550", "SN-PM-1011", 700, 3, "high", "operational", "ICU · Bed 2"),
    ("ER Triage Monitor", "Patient Monitor", "ER", "GE HealthCare", "CARESCAPE B450", "SN-PM-2012", 400, 2, "high", "under_maintenance", "ER triage"),
    ("Ward Monitor 03", "Patient Monitor", "WARD", "Philips", "IntelliVue MX450", "SN-PM-3013", 1000, 3, "medium", "operational", "Ward · Bed 12"),
    ("Syringe Pump 07", "Infusion Pump", "ICU", "Medtronic", "Alaris GH", "SN-IP-1021", 650, 2, "high", "operational", "ICU · Bed 7"),
    ("Volumetric Pump 02", "Infusion Pump", "WARD", "Medtronic", "Alaris VP", "SN-IP-3022", 800, 2, "medium", "standby", "Ward store"),
    ("AED — Main Lobby", "Defibrillator", "ER", "Philips", "HeartStart FRx", "SN-DF-2031", 1100, 5, "critical", "operational", "Lobby wall unit"),
    ("Defibrillator — OT 1", "Defibrillator", "OT", "GE HealthCare", "CARDIOSERV", "SN-DF-5032", 750, 3, "critical", "operational", "OT 1 crash cart"),
    ("Digital X-Ray — Room 1", "X-Ray", "RAD", "Siemens Healthineers", "Multix Impact", "SN-XR-4041", 1300, 5, "critical", "under_maintenance", "RAD · Room 1"),
    ("Portable X-Ray", "X-Ray", "RAD", "GE HealthCare", "Optima XR220", "SN-XR-4042", 600, 3, "high", "operational", "RAD · Mobile"),
    ("12-lead ECG — Cardiology", "ECG", "CARD", "GE HealthCare", "MAC 2000", "SN-ECG-6051", 450, 2, "medium", "operational", "CARD OPD"),
    ("ECG — Emergency", "ECG", "ER", "Philips", "PageWriter TC30", "SN-ECG-2052", 900, 2, "medium", "operational", "ER bay 2"),
    ("Ultrasound — OBG", "Ultrasound", "RAD", "Siemens Healthineers", "ACUSON Juniper", "SN-US-4061", 700, 3, "high", "operational", "RAD · Room 3"),
    ("Steam Sterilizer — CSSD", "Autoclave", "OT", "CityMed Services", "CSSD-500L", "SN-AC-5071", 1500, 2, "high", "operational", "CSSD"),
    ("Ward Monitor 09", "Patient Monitor", "WARD", "GE HealthCare", "CARESCAPE B450", "SN-PM-3019", 300, 2, "low", "standby", "Ward store"),
    ("Infusion Pump — OT 2", "Infusion Pump", "OT", "Medtronic", "Alaris GH", "SN-IP-5029", 350, 2, "high", "operational", "OT 2"),
]

PREFIX = {"Ventilator": "VEN", "Patient Monitor": "PM", "Infusion Pump": "IP", "Defibrillator": "DF",
          "X-Ray": "XR", "ECG": "ECG", "Ultrasound": "US", "Autoclave": "AC"}


class Command(BaseCommand):
    help = "Seed realistic demo equipment (idempotent)."

    def handle(self, *args, **opts):
        with transaction.atomic():
            for name, code, loc in DEPTS:
                Department.objects.get_or_create(code=code, defaults={"name": name, "location": loc})
            for c in CATS:
                Category.objects.get_or_create(name=c)
            for vname, spec in VENDORS:
                Vendor.objects.get_or_create(name=vname, defaults={"specialization": spec, "is_active": True})
            created = 0
            for i, (name, cat, dept_code, mfr, model, serial, age, wy, crit, status, loc) in enumerate(ITEMS, 1):
                if Equipment.objects.filter(serial_no=serial).exists():
                    continue
                category = Category.objects.get(name=cat)
                dept = Department.objects.get(code=dept_code)
                vendor = Vendor.objects.filter(name__icontains=mfr.split()[0]).first() or Vendor.objects.first()
                tag = f"{PREFIX[cat]}-{dept_code}-{i:03d}"
                purchase = date.today() - timedelta(days=age)
                Equipment.objects.create(
                    asset_tag=tag, name=name, category=category, department=dept,
                    manufacturer=f"{mfr} Healthcare" if "Healthcare" not in mfr and "Health" not in mfr else mfr,
                    model_no=model, serial_no=serial, purchase_date=purchase,
                    installation_date=purchase + timedelta(days=14),
                    warranty_expiry=purchase + timedelta(days=365 * wy),
                    location_detail=loc, criticality=crit, status=status,
                    last_service_date=date.today() - timedelta(days=60),
                    next_pm_date=date.today() + timedelta(days=30 if status == "operational" else -3),
                    vendor=vendor, notes="Seeded development asset — clearly demo data.",
                    is_active=True,
                )
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded {created} equipment records (skipped existing)."))
