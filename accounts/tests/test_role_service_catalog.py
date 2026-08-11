"""Role matrix catalog integrity — shared View+Edit must not recur."""

from django.test import SimpleTestCase

from accounts.role_service_catalog import (
    COLUMN_KEYS,
    FULL_ACCESS_SERVICE_KEYS,
    ROLE_SERVICE_CATALOG,
)


class RoleServiceCatalogTests(SimpleTestCase):
    def test_no_permission_mapped_to_multiple_columns_in_same_service(self):
        offenders = []
        for category in ROLE_SERVICE_CATALOG:
            for service in category["services"]:
                if service["key"] in FULL_ACCESS_SERVICE_KEYS:
                    continue
                mapped = {}
                for col in COLUMN_KEYS:
                    label = service["columns"].get(col)
                    if not label:
                        continue
                    mapped.setdefault(label, []).append(col)
                for label, cols in mapped.items():
                    if len(cols) > 1:
                        offenders.append(
                            f"{category['name']}/{service['key']}: {label} -> {cols}"
                        )
        self.assertEqual(
            offenders,
            [],
            "Services must not map the same permission to multiple CRUD columns:\n"
            + "\n".join(offenders),
        )

    def test_direct_entry_applications_exposes_all_crud_boxes(self):
        svc = next(
            s
            for cat in ROLE_SERVICE_CATALOG
            for s in cat["services"]
            if s["key"] == "direct_applications"
        )
        for col in COLUMN_KEYS:
            self.assertEqual(
                svc["columns"][col],
                "accounts.manage_direct_applications",
            )

    def test_admissions_core_services_present(self):
        keys = {
            s["key"]
            for cat in ROLE_SERVICE_CATALOG
            if cat["name"] == "Admissions"
            for s in cat["services"]
        }
        for expected in (
            "admissions_access",
            "applications",
            "direct_applications",
            "intakes",
            "academic_levels",
            "academic_years",
            "olevel_subjects",
            "alevel_subjects",
            "offer_letter_templates",
        ):
            self.assertIn(expected, keys)
