"""
Seed CourseCatalogUnit rows with representative Ndejje-style / Ugandan HE modules.

Official semester-by-semester syllabi are typically on the university LMS or faculty
handbooks; this command fills the *shared catalog* so admins can map lines to
programmes. Safe to run multiple times (get_or_create by code).

Sources consulted conceptually: public faculty pages and programme lists at
https://ndejjeuniversity.ac.ug/ — course *titles* follow common patterns for
Science & Computing, Business, Education, Engineering, and university core.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from Programs.models import CourseCatalogUnit

# (code, title, credit_units, lecture_h, practical_h, tutorial_h, description)
# contact_hours left None so model save() sums L+P+T
CATALOG = [
    # —— University-wide / foundation ——
    ("NDU-GEN101", "Communication Skills", Decimal("3"), 45, 0, 0, "English for academic and professional purposes."),
    ("NDU-GEN102", "Computer and Information Literacy", Decimal("3"), 30, 15, 0, "Productivity tools, networks, and digital citizenship."),
    ("NDU-GEN103", "Critical Thinking and Study Skills", Decimal("2"), 30, 0, 0, ""),
    ("NDU-GEN104", "Ugandan History, Government and Society", Decimal("3"), 45, 0, 0, ""),
    ("NDU-GEN105", "Ethics and Professional Conduct", Decimal("2"), 30, 0, 0, ""),
    ("NDU-GEN106", "Statistics for Decision Making", Decimal("3"), 45, 0, 0, ""),
    ("NDU-GEN107", "Research Methods (Introductory)", Decimal("3"), 45, 0, 0, ""),
    ("NDU-GEN108", "Entrepreneurship and Innovation", Decimal("2"), 30, 0, 0, ""),
    # —— Mathematics ——
    ("NDU-MTH101", "Algebra and Trigonometry", Decimal("3"), 45, 0, 0, ""),
    ("NDU-MTH102", "Calculus I", Decimal("4"), 60, 0, 0, ""),
    ("NDU-MTH103", "Calculus II", Decimal("4"), 60, 0, 0, ""),
    ("NDU-MTH201", "Linear Algebra", Decimal("3"), 45, 0, 0, ""),
    ("NDU-MTH202", "Probability and Statistics", Decimal("3"), 45, 0, 0, ""),
    ("NDU-MTH203", "Numerical Methods", Decimal("3"), 45, 0, 0, ""),
    # —— Basic sciences ——
    ("NDU-PHY101", "Mechanics and Properties of Matter", Decimal("3"), 45, 15, 0, ""),
    ("NDU-PHY102", "Electricity and Magnetism", Decimal("3"), 45, 15, 0, ""),
    ("NDU-CHM101", "General Chemistry I", Decimal("3"), 45, 15, 0, ""),
    ("NDU-CHM102", "General Chemistry II", Decimal("3"), 45, 15, 0, ""),
    ("NDU-BIO101", "Cell Biology and Genetics", Decimal("3"), 45, 15, 0, ""),
    ("NDU-BIO102", "Diversity of Life and Ecology", Decimal("3"), 45, 15, 0, ""),
    # —— Science & Computing ——
    ("NDU-CSC101", "Introduction to Computing", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC102", "Programming Fundamentals", Decimal("4"), 30, 30, 0, ""),
    ("NDU-CSC103", "Discrete Structures for Computing", Decimal("3"), 45, 0, 0, ""),
    ("NDU-CSC201", "Data Structures and Algorithms", Decimal("4"), 30, 30, 0, ""),
    ("NDU-CSC202", "Database Systems", Decimal("4"), 30, 30, 0, ""),
    ("NDU-CSC203", "Computer Organisation and Architecture", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC204", "Operating Systems", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC205", "Object-Oriented Systems Development", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC301", "Software Engineering", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC302", "Data Communications and Networks", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC303", "Web Technologies", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC304", "Information Security Fundamentals", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC305", "Mobile Application Development", Decimal("3"), 30, 15, 0, ""),
    ("NDU-CSC306", "Systems Analysis and Design", Decimal("3"), 45, 0, 0, ""),
    ("NDU-CSC401", "Final Year Project I", Decimal("3"), 0, 90, 0, "Supervised project."),
    ("NDU-CSC402", "Final Year Project II", Decimal("3"), 0, 90, 0, "Supervised project."),
    ("NDU-DST201", "Introduction to Data Science", Decimal("3"), 30, 15, 0, ""),
    ("NDU-DST301", "Machine Learning Fundamentals", Decimal("3"), 30, 15, 0, ""),
    # —— Business & Management ——
    ("NDU-BUS101", "Principles of Management", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS102", "Principles of Accounting", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS103", "Business Mathematics", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS104", "Microeconomics", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS105", "Macroeconomics", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS201", "Marketing Management", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS202", "Human Resource Management", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS203", "Financial Management", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS204", "Business Law", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS301", "Operations and Supply Chain Management", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS302", "Organisational Behaviour", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS303", "Strategic Management", Decimal("3"), 45, 0, 0, ""),
    ("NDU-BUS304", "International Business", Decimal("2"), 30, 0, 0, ""),
    ("NDU-BUS401", "Project / Field Study (Business)", Decimal("4"), 0, 120, 0, ""),
    # —— Education ——
    ("NDU-EDU101", "Foundations of Education", Decimal("3"), 45, 0, 0, ""),
    ("NDU-EDU102", "Educational Psychology", Decimal("3"), 45, 0, 0, ""),
    ("NDU-EDU103", "Curriculum Studies", Decimal("3"), 45, 0, 0, ""),
    ("NDU-EDU201", "Pedagogy and Instructional Methods", Decimal("3"), 45, 0, 0, ""),
    ("NDU-EDU202", "Assessment in Education", Decimal("3"), 45, 0, 0, ""),
    ("NDU-EDU203", "Educational Management and Leadership", Decimal("3"), 45, 0, 0, ""),
    ("NDU-EDU301", "Teaching Practice I", Decimal("3"), 0, 135, 0, ""),
    ("NDU-EDU302", "Teaching Practice II", Decimal("3"), 0, 135, 0, ""),
    # —— Engineering (intro / common) ——
    ("NDU-ENG101", "Engineering Drawing", Decimal("3"), 30, 30, 0, ""),
    ("NDU-ENG102", "Engineering Mechanics — Statics", Decimal("4"), 45, 15, 0, ""),
    ("NDU-ENG103", "Engineering Materials", Decimal("3"), 45, 0, 0, ""),
    ("NDU-ENG201", "Electrical Circuits Analysis", Decimal("4"), 30, 30, 0, ""),
    ("NDU-ENG202", "Thermodynamics", Decimal("4"), 45, 15, 0, ""),
    ("NDU-ENG203", "Fluid Mechanics", Decimal("4"), 45, 15, 0, ""),
    ("NDU-ENG301", "Engineering Design Studio", Decimal("3"), 20, 40, 0, ""),
]


class Command(BaseCommand):
    help = "Insert representative Ndejje-aligned course catalog units (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        created_n = 0
        existing_n = 0

        for row in CATALOG:
            code, title, cu, lh, ph, th, desc = row

            defaults = {
                "title": title,
                "description": desc or "",
                "credit_units": cu,
                "lecture_hours": lh if lh else None,
                "practical_hours": ph if ph else None,
                "tutorial_hours": th if th else None,
                "contact_hours": None,
                "is_active": True,
            }

            if dry:
                exists = CourseCatalogUnit.objects.filter(code=code).exists()
                self.stdout.write(
                    f"{'skip (exists)' if exists else 'would create'} {code} — {title}"
                )
                continue

            obj, was_created = CourseCatalogUnit.objects.get_or_create(
                code=code,
                defaults=defaults,
            )
            if was_created:
                created_n += 1
                self.stdout.write(self.style.SUCCESS(f"+ {code} — {title}"))
            else:
                existing_n += 1
                self.stdout.write(f"  (exists) {code}")

        if dry:
            self.stdout.write(self.style.WARNING("Dry run — no database changes."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Created {created_n}, already present {existing_n}."
                )
            )
