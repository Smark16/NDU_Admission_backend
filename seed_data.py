"""
Run with: python manage.py shell < seed_data.py
"""
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ndu_portal.settings')

from accounts.models import Campus
from admissions.models import AcademicLevel, Faculty, OLevelSubject, ALevelSubject
from Programs.models import Program

print("=" * 50)
print("Seeding dummy data...")
print("=" * 50)

# ── 1. Campus ────────────────────────────────────────
campus, _ = Campus.objects.get_or_create(
    name="Main Campus",
    defaults={"code": "MAIN", "address": "Ndejje, Luwero Road", "email": "main@ndejje.ac.ug"}
)
print(f"✓ Campus: {campus.name}")

# ── 2. Academic Levels ────────────────────────────────
levels_data = [
    {"name": "Certificate",   "is_active": True},
    {"name": "Diploma",       "is_active": True},
    {"name": "Undergraduate", "is_active": True},
    {"name": "Graduate",      "is_active": True},
]
levels = {}
for d in levels_data:
    lvl, _ = AcademicLevel.objects.get_or_create(name=d["name"], defaults={"is_active": d["is_active"]})
    levels[d["name"]] = lvl
    print(f"✓ Academic Level: {lvl.name}")

# ── 3. Faculties ──────────────────────────────────────
faculties_data = [
    {"name": "Faculty of Business and Management",        "code": "FBM"},
    {"name": "Faculty of Education",                      "code": "FED"},
    {"name": "Faculty of Computing and Informatics",      "code": "FCI"},
    {"name": "Faculty of Engineering and Applied Sciences","code": "FEA"},
    {"name": "Faculty of Science",                        "code": "FSC"},
]
faculties = {}
for d in faculties_data:
    fac, _ = Faculty.objects.get_or_create(
        name=d["name"],
        defaults={"code": d["code"], "is_active": True}
    )
    fac.campuses.add(campus)
    faculties[d["name"]] = fac
    print(f"✓ Faculty: {fac.name}")

# ── 4. Programs ───────────────────────────────────────
programs_data = [
    # Business
    {"name": "Bachelor of Business Administration", "short_form": "BBA", "code": "BBA001",
     "faculty": "Faculty of Business and Management", "level": "Undergraduate", "min_years": 3, "max_years": 4},
    {"name": "Diploma in Business Administration",  "short_form": "DBA", "code": "DBA001",
     "faculty": "Faculty of Business and Management", "level": "Diploma", "min_years": 2, "max_years": 2},
    # Education
    {"name": "Bachelor of Education (Arts)",        "short_form": "BEd(A)", "code": "BED001",
     "faculty": "Faculty of Education", "level": "Undergraduate", "min_years": 3, "max_years": 4},
    {"name": "Diploma in Education (Secondary)",    "short_form": "DipEd", "code": "DED001",
     "faculty": "Faculty of Education", "level": "Diploma", "min_years": 2, "max_years": 2},
    # Computing
    {"name": "Bachelor of Science in Computer Science", "short_form": "BSc.CS", "code": "BSC001",
     "faculty": "Faculty of Computing and Informatics", "level": "Undergraduate", "min_years": 3, "max_years": 4},
    {"name": "Diploma in Information Technology",   "short_form": "DIT", "code": "DIT001",
     "faculty": "Faculty of Computing and Informatics", "level": "Diploma", "min_years": 2, "max_years": 2},
    # Engineering
    {"name": "Bachelor of Engineering (Civil)",     "short_form": "BEng(Civil)", "code": "BEC001",
     "faculty": "Faculty of Engineering and Applied Sciences", "level": "Undergraduate", "min_years": 4, "max_years": 5},
    # Science
    {"name": "Bachelor of Science (Biology)",       "short_form": "BSc(Bio)", "code": "BSB001",
     "faculty": "Faculty of Science", "level": "Undergraduate", "min_years": 3, "max_years": 4},
    # Graduate
    {"name": "Master of Business Administration",   "short_form": "MBA", "code": "MBA001",
     "faculty": "Faculty of Business and Management", "level": "Graduate", "min_years": 2, "max_years": 3},
]
for d in programs_data:
    prog, created = Program.objects.get_or_create(
        code=d["code"],
        defaults={
            "name": d["name"],
            "short_form": d["short_form"],
            "faculty": faculties[d["faculty"]],
            "academic_level": levels[d["level"]],
            "min_years": d["min_years"],
            "max_years": d["max_years"],
            "is_active": True,
        }
    )
    prog.campuses.add(campus)
    print(f"✓ Program: {prog.name}")

# ── 5. O-Level Subjects ───────────────────────────────
olevel_subjects = [
    ("English Language",   "ENG"),
    ("Mathematics",        "MTH"),
    ("Physics",            "PHY"),
    ("Chemistry",          "CHE"),
    ("Biology",            "BIO"),
    ("History",            "HIS"),
    ("Geography",          "GEO"),
    ("Agriculture",        "AGR"),
    ("Commerce",           "COM"),
    ("Computer Studies",   "CMP"),
    ("Christian Religious Education", "CRE"),
    ("Fine Art",           "FAT"),
]
for name, code in olevel_subjects:
    subj, _ = OLevelSubject.objects.get_or_create(code=code, defaults={"name": name})
    print(f"✓ O-Level: {subj.name}")

# ── 6. A-Level Subjects ───────────────────────────────
alevel_subjects = [
    ("Mathematics",        "MTH"),
    ("Physics",            "PHY"),
    ("Chemistry",          "CHE"),
    ("Biology",            "BIO"),
    ("History",            "HIS"),
    ("Geography",          "GEO"),
    ("Economics",          "ECO"),
    ("Entrepreneurship",   "ENT"),
    ("ICT",                "ICT"),
    ("General Paper",      "GP"),
    ("Divinity",           "DIV"),
    ("Literature in English", "LIT"),
]
for name, code in alevel_subjects:
    subj, _ = ALevelSubject.objects.get_or_create(code=code, defaults={"name": name})
    print(f"✓ A-Level: {subj.name}")

print("=" * 50)
print("✓ Done! All seed data loaded.")
print("=" * 50)
