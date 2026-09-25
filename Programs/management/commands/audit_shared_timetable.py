"""
Read-only audit of shared/cross-cutting timetable state.

Run on the server:
    cd /home/admissions/NDU_Admission_backend
    source venv/bin/activate
    python manage.py audit_shared_timetable
    python manage.py audit_shared_timetable --json > audit_2026_09_08.json
    python manage.py audit_shared_timetable --days 30 --limit 30

This command makes NO writes. It only reads via the ORM. Safe to run
repeatedly on production to track progress over time (e.g. re-run monthly
and diff the unlinked-cluster count).

Name matching for unlinked clusters is exact-normalized only (lowered/stripped).
Treat that list as a Timetable Office review queue, not an auto-link source.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from Programs.models import CourseUnit, SharedTeachingOffering, TimetableSession


class Command(BaseCommand):
    help = "Read-only audit of shared/cross-cutting timetable linking and mirror usage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=14,
            help="Window (days) for 'recent activity' section. Default 14.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Max number of unlinked clusters / top offerings to print. Default 20.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON instead of a human-readable report.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        limit = options["limit"]
        as_json = options["json"]

        report = {
            "generated_at": timezone.now().isoformat(),
            "window_days": days,
        }

        report["offerings"] = self._audit_offerings()
        report["mirror_usage"] = self._audit_mirror_usage(limit)
        report["unlinked_clusters"] = self._audit_unlinked_clusters(limit)
        report["recent_activity"] = self._audit_recent_activity(days)

        if as_json:
            self.stdout.write(json.dumps(report, indent=2, default=str))
        else:
            self._print_human(report, limit)

    # ---------- sections ----------

    def _audit_offerings(self):
        active_stos = SharedTeachingOffering.objects.filter(is_active=True).count()
        cus_on_sto = CourseUnit.objects.filter(
            shared_teaching_offering_id__isnull=False, is_active=True
        ).count()

        top_offerings = []
        qs = (
            SharedTeachingOffering.objects.filter(is_active=True)
            .annotate(n=Count("course_units"))
            .filter(n__gte=2)
            .order_by("-n")
        )
        for sto in qs[:20]:
            top_offerings.append(
                {
                    "id": sto.id,
                    "code": getattr(sto, "code", None),
                    "name": getattr(sto, "name", None),
                    "linked_units": sto.n,
                }
            )

        return {
            "active_shared_teaching_offerings": active_stos,
            "course_units_linked_to_an_offering": cus_on_sto,
            "top_offerings_by_linked_unit_count": top_offerings,
        }

    def _audit_mirror_usage(self, limit):
        qs = TimetableSession.objects.filter(
            is_active=True, notes__icontains="Mirrored from shared teaching"
        ).select_related("course_unit", "course_unit__program_batch__program")

        total = qs.count()
        examples = []
        for s in qs[:limit]:
            program = getattr(
                getattr(s.course_unit, "program_batch", None), "program", None
            )
            examples.append(
                {
                    "session_id": s.id,
                    "course_unit_code": getattr(s.course_unit, "code", None),
                    "programme": getattr(program, "name", None),
                    "day_of_week": getattr(s, "day_of_week", None),
                    "start_time": str(getattr(s, "start_time", "")),
                    "notes_excerpt": (s.notes or "")[:80],
                }
            )

        return {
            "sessions_with_mirror_note": total,
            "examples": examples,
        }

    def _audit_unlinked_clusters(self, limit):
        """
        Group active course units by normalized name across programmes.
        A cluster is 'at risk' if it spans >=2 programmes AND at least one
        of those course units has no shared_teaching_offering_id.
        """
        buckets = defaultdict(list)
        qs = CourseUnit.objects.filter(is_active=True).select_related(
            "program_batch__program", "shared_teaching_offering"
        )
        for cu in qs:
            name = (getattr(cu, "name", "") or "").strip().lower()
            if not name:
                continue
            program = getattr(getattr(cu, "program_batch", None), "program", None)
            buckets[name].append(
                {
                    "cu_id": cu.id,
                    "code": getattr(cu, "code", None),
                    "programme": getattr(program, "name", None),
                    "sto_id": getattr(cu, "shared_teaching_offering_id", None),
                }
            )

        multi_programme = {
            name: rows
            for name, rows in buckets.items()
            if len({r["programme"] for r in rows if r["programme"]}) >= 2
        }

        unlinked_clusters = []
        for name, rows in multi_programme.items():
            sto_ids = {r["sto_id"] for r in rows}
            if None in sto_ids and len(rows) >= 2:
                unlinked_clusters.append(
                    {
                        "name": name,
                        "unit_count": len(rows),
                        "distinct_sto_ids": sorted(
                            [s for s in sto_ids if s is not None]
                        ),
                        "has_fully_unlinked_units": True,
                        "units": rows,
                    }
                )

        unlinked_clusters.sort(key=lambda c: -c["unit_count"])

        return {
            "multi_programme_name_clusters": len(multi_programme),
            "clusters_with_at_least_one_unlinked_unit": len(unlinked_clusters),
            "top_clusters": unlinked_clusters[:limit],
        }

    def _audit_recent_activity(self, days):
        since = timezone.now() - timedelta(days=days)
        qs = TimetableSession.objects.filter(updated_at__gte=since, is_active=True)
        return {
            "sessions_touched": qs.count(),
            "draft_unpublished": qs.filter(is_published=False).count(),
            "on_shared_offering": qs.filter(
                course_unit__shared_teaching_offering_id__isnull=False
            ).count(),
        }

    # ---------- output ----------

    def _print_human(self, report, limit):
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("Shared Timetable Audit"))
        w(f"Generated: {report['generated_at']}")
        w("")

        o = report["offerings"]
        w(self.style.MIGRATE_HEADING("Offerings"))
        w(f"  Active SharedTeachingOfferings: {o['active_shared_teaching_offerings']}")
        w(f"  Course units linked to an offering: {o['course_units_linked_to_an_offering']}")
        if o["top_offerings_by_linked_unit_count"]:
            w("  Top offerings by linked unit count:")
            for row in o["top_offerings_by_linked_unit_count"]:
                w(
                    f"    - [{row['id']}] {row['code']} {row['name']} — "
                    f"{row['linked_units']} units"
                )
        w("")

        m = report["mirror_usage"]
        w(self.style.MIGRATE_HEADING("Mirror usage (live evidence)"))
        w(f"  Sessions with a 'mirrored' note: {m['sessions_with_mirror_note']}")
        for ex in m["examples"][:10]:
            w(
                f"    - session {ex['session_id']} | {ex['course_unit_code']} | "
                f"{ex['programme']} | day {ex['day_of_week']} {ex['start_time']} | "
                f"{ex['notes_excerpt']}"
            )
        w("")

        u = report["unlinked_clusters"]
        w(self.style.MIGRATE_HEADING("Unlinked / lookalike clusters"))
        w(f"  Multi-programme name clusters: {u['multi_programme_name_clusters']}")
        w(
            f"  Clusters with >=1 unlinked unit: "
            f"{u['clusters_with_at_least_one_unlinked_unit']}  "
            f"(THIS is the migration queue size)"
        )
        if u["top_clusters"]:
            w(f"  Top {limit} clusters:")
            for c in u["top_clusters"]:
                progs = ", ".join(sorted({r["programme"] or "?" for r in c["units"]}))
                w(f"    - '{c['name']}' — {c['unit_count']} units across [{progs}]")
        w("")

        a = report["recent_activity"]
        w(self.style.MIGRATE_HEADING(f"Recent activity (last {report['window_days']} days)"))
        w(f"  Sessions touched: {a['sessions_touched']}")
        w(f"  Draft/unpublished: {a['draft_unpublished']}")
        w(f"  On a shared offering: {a['on_shared_offering']}")
        w("")
        w(self.style.SUCCESS("Audit complete. No data was modified."))
