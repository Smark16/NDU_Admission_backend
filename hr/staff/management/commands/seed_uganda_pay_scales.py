"""Seed Ugandan public-university style pay scales (IPPS U-grades and support P-grades)."""
from django.core.management.base import BaseCommand

from hr.staff.models import PayScale

# Typical Ugandan university / MoPS-aligned scale ladder (customise per institution policy).
UGANDA_PAY_SCALES = [
    # Support (P scales — often used for manual / junior support cadre)
    ("P1", "Scale P1 — Entry support", "SUPPORT", 1, "Cleaner, Gardener, Casual worker"),
    ("P2", "Scale P2 — Junior support", "SUPPORT", 2, "Office attendant, Driver"),
    ("P3", "Scale P3 — Skilled support", "SUPPORT", 3, "Artisan, Senior driver, Security supervisor"),
    ("P4", "Scale P4 — Senior support", "SUPPORT", 4, "Senior artisan, Head driver"),
    ("P5", "Scale P5 — Chief support", "SUPPORT", 5, "Chief artisan, Facilities supervisor"),
    # University administrative & academic (U scales — IPPS-style)
    ("U1", "Scale U1 — Entry administrative", "ADMINISTRATIVE", 10, "Clerk, Records assistant"),
    ("U2", "Scale U2 — Administrative assistant", "ADMINISTRATIVE", 11, "Administrative assistant, Typist"),
    ("U3", "Scale U3 — Senior clerk", "ADMINISTRATIVE", 12, "Senior clerk, Accounts assistant"),
    ("U4", "Scale U4 — Principal administrative officer", "ADMINISTRATIVE", 13, "Principal administrative officer"),
    ("U5", "Scale U5 — Senior administrative officer", "ADMINISTRATIVE", 14, "Senior PAO, Section head (admin)"),
    ("U6", "Scale U6 — Graduate / tutorial entry", "ACADEMIC", 15, "Graduate assistant, Research assistant"),
    ("U7", "Scale U7 — Tutorial assistant", "ACADEMIC", 16, "Tutorial assistant, Instructor"),
    ("U8", "Scale U8 — Assistant lecturer", "ACADEMIC", 17, "Assistant lecturer"),
    ("U9", "Scale U9 — Lecturer", "ACADEMIC", 18, "Lecturer"),
    ("U10", "Scale U10 — Senior lecturer", "ACADEMIC", 19, "Senior lecturer"),
    ("U11", "Scale U11 — Associate professor", "ACADEMIC", 20, "Associate professor, Reader"),
    ("U12", "Scale U12 — Professor", "ACADEMIC", 21, "Professor"),
    ("U13", "Scale U13 — Principal officer", "ADMINISTRATIVE", 22, "Principal officer, Faculty administrator"),
    ("U14", "Scale U14 — Senior principal officer", "ADMINISTRATIVE", 23, "Senior principal officer, Dean (admin)"),
    ("U15", "Scale U15 — Deputy head of unit", "ADMINISTRATIVE", 24, "Deputy registrar, Deputy bursar, Deputy dean"),
    ("U16", "Scale U16 — Head of unit", "ADMINISTRATIVE", 25, "Registrar, Bursar, Dean, DVC"),
    ("U17", "Scale U17 — Chief executive", "ADMINISTRATIVE", 26, "Vice Chancellor, University Secretary"),
]


class Command(BaseCommand):
    help = "Seed Ugandan-style university pay scales (P1–P5 support, U1–U17 IPPS-style)."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for code, name, category, rank_order, typical_roles in UGANDA_PAY_SCALES:
            _, was_created = PayScale.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "rank_order": rank_order,
                    "typical_roles": typical_roles,
                    "description": (
                        f"Ugandan public university pay scale {code}. "
                        "Align step/notch and basic salary with your current IPPS / council resolution."
                    ),
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Pay scales ready: {created} created, {updated} updated ({len(UGANDA_PAY_SCALES)} total)."
            )
        )
