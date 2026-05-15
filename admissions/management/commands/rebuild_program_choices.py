import re
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.models import Application, ApplicationProgramChoice
from Programs.models import Program


class Command(BaseCommand):
    help = "Intelligently rebuild missing program choices with high accuracy"

    def normalize(self, text):
        if not text:
            return ""
        return re.sub(r'[^a-z0-9\s]', '', str(text).lower().strip())

    # ====================== ENHANCED KEYWORDS ======================
    PROGRAM_KEYWORDS = {
        "computer_science": [
            "computer science", "software engineering", "information technology",
            "information systems", "business computing", "ict", "computing",
            "data science", "cyber security", "artificial intelligence", "software",
        ],
        "engineering": [
            "engineering", "civil engineering", "electrical engineering", 
            "mechanical engineering", "geomatics", "land surveying", "surveying",
            "biomedical engineering", "building engineering", "telecommunication",
        ],
        "business": [
            "business", "commerce", "accounting", "finance", "banking", "marketing",
            "human resource", "procurement", "supply chain", "logistics", "economics",
            "project management", "entrepreneurship", "microfinance", "administration",
        ],
        "education": [
            "education", "teacher", "teaching", "pedagogy", "early childhood",
            "primary education", "secondary education", "curriculum", "guidance",
        ],
        "health": [
            "clinical medicine", "nursing", "pharmacy", "medical laboratory",
            "public health", "health science", "biomedical", "medicine",
        ],
        "agriculture": [
            "agriculture", "agribusiness", "animal production", "crop science",
            "forestry", "environmental science", "sustainable agriculture",
        ],
        "law": ["law", "legal", "bachelor of laws", "llb"],
        "humanities": [
            "development studies", "social work", "journalism", "mass communication",
            "public relations", "psychology", "community development", "gender studies",
            "peace studies", "arts", "humanities",
        ],
    }

    # ====================== IMPROVED COMBINATION MAP ======================
    COMBINATION_MAP = {
        # Science Combinations
        "pcm": ["engineering", "computer_science", "health"],
        "pmc": ["engineering", "computer_science"],
        "pcb": ["health", "computer_science"],
        "bcm": ["health", "business"],
        "mpc": ["engineering", "computer_science"],

        # Arts Combinations
        "heg": ["humanities", "law", "education"],
        "bag": ["education", "humanities", "business"],
        "art": ["humanities", "education"],
        "geg": ["education", "humanities"],

        # Business & Others
        "meg": ["business"],
        "peg": ["business", "education"],
    }

    def get_best_matches(self, app, programs):
        scored = []

        for program in programs:
            score = self.score_program(app, program)
            if score > 0:
                scored.append((program, score))

        # Sort by score (descending)
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def score_program(self, app, program):
        score = 0
        pname = self.normalize(program.name)
        faculty = self.normalize(getattr(program, 'faculty', None))

        # 1. Academic Level Match (Very High Weight)
        if app.academic_level:
            level_name = self.normalize(app.academic_level.name)
            prog_name = pname

            if "bachelor" in level_name or "degree" in level_name:
                if any(x in prog_name for x in ["bachelor", "degree", "bsc", "ba", "b.a", "b.sc"]):
                    score += 100
            elif "diploma" in level_name:
                if "diploma" in prog_name:
                    score += 100
            elif "certificate" in level_name:
                if "certificate" in prog_name:
                    score += 100

        # 2. Campus Match
        if app.campus and hasattr(program, 'campuses'):
            try:
                if program.campuses.filter(id=app.campus.id).exists():
                    score += 60
            except:
                pass

        # 3. A-Level Combination Match (High Weight)
        combo = self.normalize(app.alevel_combination or "")
        if combo in self.COMBINATION_MAP:
            for group in self.COMBINATION_MAP[combo]:
                for keyword in self.PROGRAM_KEYWORDS.get(group, []):
                    if keyword in pname:
                        score += 75

        # 4. Direct Keyword Matching (Strong Signal)
        direct_keywords = {
            "computer": ["computer science", "software engineering", "information technology", "ict"],
            "engineering": ["engineering", "civil", "electrical", "mechanical", "geomatics"],
            "business": ["business", "commerce", "accounting", "finance", "marketing"],
            "health": ["clinical medicine", "nursing", "pharmacy", "medical laboratory"],
            "education": ["education", "teacher", "teaching"],
            "law": ["law", "legal"],
            "agriculture": ["agriculture", "agribusiness"],
        }

        for category, keywords in direct_keywords.items():
            for kw in keywords:
                if kw in pname:
                    score += 65

        # 5. Faculty Bonus
        if faculty:
            if "engineering" in faculty:
                score += 40
            elif "science" in faculty or "computing" in faculty:
                score += 35
            elif "business" in faculty:
                score += 30

        return score

    @transaction.atomic
    def handle(self, *args, **kwargs):
        # Get applications without program choices
        applications = Application.objects.filter(
            status="submitted"
        ).exclude(
            program_choices__isnull=False
        ).select_related('academic_level', 'campus')

        programs = list(Program.objects.select_related('faculty').prefetch_related('campuses'))

        self.stdout.write(self.style.WARNING(
            f"Found {applications.count()} applications without program choices."
        ))

        created_total = 0

        for app in applications:
            scored_programs = self.get_best_matches(app, programs)

            # Take top 3 best matches
            selected = [prog for prog, score in scored_programs[:3]]

            # Fallback: If less than 2 good matches, add generic ones
            if len(selected) < 2:
                fallback = Program.objects.all()[:5]
                for p in fallback:
                    if p not in selected:
                        selected.append(p)
                    if len(selected) >= 3:
                        break

            # Save choices
            bulk = [
                ApplicationProgramChoice(
                    application=app,
                    program=program,
                    choice_order=idx + 1
                )
                for idx, program in enumerate(selected)
            ]

            if bulk:
                ApplicationProgramChoice.objects.bulk_create(bulk)
                created_total += len(bulk)

                self.stdout.write(self.style.SUCCESS(
                    f"✓ Assigned {len(bulk)} programs to {app.full_name} (ID: {app.id})"
                ))
                for choice in bulk:
                    self.stdout.write(f"   → {choice.program.name}")

        self.stdout.write(self.style.SUCCESS(f"\n🎉 DONE! Created {created_total} program choices."))