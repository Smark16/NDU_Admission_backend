"""Predefined Django groups for Finance, Academics, User Admin, and Audit teams.

Admissions, Examinations, and Graduation roles live in their own app role_setup modules.
Run: python manage.py seed_team_roles
"""

# (group_name, list of (app_label, codename))
ERP_TEAM_ROLE_MATRIX = {
    # ── Finance ──────────────────────────────────────────────────────────────
    "Finance Manager": [
        ("accounts", "access_finance"),
        ("accounts", "access_reports"),
        ("accounts", "configure_fee_plans"),
        ("accounts", "manage_payment_reconciliation"),
        ("admissions", "view_admittedstudent"),
        ("payments", "view_applicationpayment"),
        ("payments", "change_applicationpayment"),
        ("payments", "view_studenttuitionpayment"),
        ("payments", "change_studenttuitionpayment"),
        ("payments", "view_applicationfee"),
        ("payments", "change_applicationfee"),
        ("payments", "view_feehead"),
        ("payments", "change_feehead"),
        ("payments", "view_feeplan"),
        ("payments", "change_feeplan"),
        ("payments", "view_feeplanrule"),
        ("payments", "change_feeplanrule"),
        ("payments", "view_registrationsettings"),
        ("payments", "change_registrationsettings"),
        ("payments", "view_tuitionledger"),
    ],
    "Finance Officer": [
        # Operational finance: student directory, tuition matrices, ad-hoc charges, payments
        ("accounts", "access_finance"),
        ("accounts", "configure_fee_plans"),
        ("admissions", "view_admittedstudent"),
        ("Programs", "view_program"),
        ("Programs", "view_programbatch"),
        ("payments", "view_applicationpayment"),
        ("payments", "change_applicationpayment"),
        ("payments", "view_studenttuitionpayment"),
        ("payments", "change_studenttuitionpayment"),
        ("payments", "view_applicationfee"),
        ("payments", "change_applicationfee"),
        ("payments", "view_feehead"),
        ("payments", "change_feehead"),
        ("payments", "add_feehead"),
        ("payments", "view_feeplan"),
        ("payments", "change_feeplan"),
        ("payments", "add_feeplan"),
        ("payments", "view_feeplanrule"),
        ("payments", "change_feeplanrule"),
        ("payments", "add_feeplanrule"),
        ("payments", "view_tuitionledger"),
    ],
    "Finance Viewer": [
        ("accounts", "access_finance"),
        ("accounts", "access_reports"),
        ("payments", "view_applicationpayment"),
        ("payments", "view_studenttuitionpayment"),
        ("payments", "view_applicationfee"),
        ("payments", "view_feehead"),
        ("payments", "view_feeplan"),
        ("payments", "view_feeplanrule"),
        ("payments", "view_tuitionledger"),
    ],
    "Fee Configuration Officer": [
        ("accounts", "configure_fee_plans"),
        ("payments", "view_applicationfee"),
        ("payments", "change_applicationfee"),
        ("payments", "add_applicationfee"),
        ("payments", "view_feehead"),
        ("payments", "change_feehead"),
        ("payments", "add_feehead"),
        ("payments", "view_feeplan"),
        ("payments", "change_feeplan"),
        ("payments", "add_feeplan"),
        ("payments", "view_feeplanrule"),
        ("payments", "change_feeplanrule"),
        ("payments", "add_feeplanrule"),
        ("payments", "view_registrationsettings"),
        ("payments", "change_registrationsettings"),
    ],
    "Payment Reconciliation Officer": [
        ("accounts", "manage_payment_reconciliation"),
        ("accounts", "access_finance"),
        ("payments", "view_applicationpayment"),
        ("payments", "change_applicationpayment"),
        ("payments", "view_studenttuitionpayment"),
        ("payments", "change_studenttuitionpayment"),
    ],
    # ── Academics / Registry ───────────────────────────────────────────────────
    "Academic Programme Viewer": [
        ("accounts", "access_academics"),
        ("Programs", "view_program"),
        ("Programs", "view_programbatch"),
        ("Programs", "view_courseunit"),
        ("Programs", "view_semester"),
        ("admissions", "view_faculty"),
        ("accounts", "view_campus"),
    ],
    "Curriculum Manager": [
        ("accounts", "access_academics"),
        ("accounts", "manage_curriculum"),
        ("Programs", "view_program"),
        ("Programs", "view_programbatch"),
        ("Programs", "view_courseunit"),
    ],
    "Scheduling Officer": [
        ("accounts", "access_academics"),
        ("accounts", "manage_program_scheduling"),
        ("Programs", "view_program"),
        ("Programs", "view_programbatch"),
        ("Programs", "change_programbatch"),
        ("Programs", "view_semester"),
        ("Programs", "change_semester"),
        ("Programs", "view_courseunit"),
        ("Programs", "change_courseunit"),
    ],
    "Enrollment Officer": [
        ("accounts", "access_academics"),
        ("accounts", "manage_academic_enrollment"),
        ("Programs", "view_program"),
        ("Programs", "view_programbatch"),
        ("admissions", "view_admissionchangerequest"),
        ("admissions", "manage_admission_change_requests"),
        ("admissions", "view_admittedstudent"),
    ],
    "Course Catalog Manager": [
        ("accounts", "access_academics"),
        ("accounts", "manage_course_catalog"),
        ("Programs", "view_program"),
        ("Programs", "view_courseunit"),
        ("Programs", "change_courseunit"),
        ("Programs", "add_courseunit"),
    ],
    # ── User admin / ICT ───────────────────────────────────────────────────────
    "User Administrator": [
        ("accounts", "access_user_management"),
        ("accounts", "assign_roles"),
        ("accounts", "view_user"),
        ("accounts", "add_user"),
        ("accounts", "change_user"),
        ("auth", "view_group"),
        ("auth", "add_group"),
        ("auth", "change_group"),
    ],
    "System Settings Officer": [
        ("accounts", "access_system_settings"),
        ("accounts", "manage_communication_templates"),
        ("admissions", "view_emailtemplate"),
        ("admissions", "change_emailtemplate"),
        # Subjects & Templates (offer letter PDF mapper) — not the same as email templates
        ("AdmissionReports", "view_setup"),
        ("AdmissionLetter", "view_offerlettertemplate"),
        ("AdmissionLetter", "add_offerlettertemplate"),
        ("AdmissionLetter", "change_offerlettertemplate"),
        ("AdmissionLetter", "delete_offerlettertemplate"),
        ("accounts", "view_campus"),
        ("accounts", "change_campus"),
    ],
    "Offer Letter Template Manager": [
        ("AdmissionReports", "view_setup"),
        ("AdmissionLetter", "view_offerlettertemplate"),
        ("AdmissionLetter", "add_offerlettertemplate"),
        ("AdmissionLetter", "change_offerlettertemplate"),
        ("AdmissionLetter", "delete_offerlettertemplate"),
        ("admissions", "view_admittedstudent"),
        ("Programs", "view_program"),
    ],
    # ── Audit ──────────────────────────────────────────────────────────────────
    "Auditor": [
        ("accounts", "access_audit"),
        ("accounts", "access_reports"),
        ("audit", "view_auditlog"),
    ],
}

ERP_STAFF_ROLE_NAMES = frozenset(ERP_TEAM_ROLE_MATRIX.keys())

PERMISSION_APPS = (
    "accounts",
    "auth",
    "admissions",
    "AdmissionReports",
    "AdmissionLetter",
    "payments",
    "Programs",
    "audit",
)


def get_permission(Permission, app_label: str, codename: str):
    perm = Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).first()
    if perm:
        return perm
    perm = Permission.objects.filter(
        content_type__app_label=app_label.lower(), codename=codename
    ).first()
    if perm:
        return perm
    return Permission.objects.filter(codename=codename).first()


def seed_erp_team_role_group(Group, Permission, group_name: str, *, stdout=None):
    perms = ERP_TEAM_ROLE_MATRIX.get(group_name)
    if not perms:
        raise ValueError(f"Unknown ERP team role: {group_name}")

    group, created = Group.objects.get_or_create(name=group_name)
    added = 0
    for app_label, codename in perms:
        perm = get_permission(Permission, app_label, codename)
        if perm and not group.permissions.filter(pk=perm.pk).exists():
            group.permissions.add(perm)
            added += 1
    if stdout:
        verb = "Created" if created else "Updated"
        stdout.write(f"{verb} group: {group_name} (+{added} permissions)")
    return group


def seed_all_erp_team_roles(Group, Permission, *, stdout=None):
    groups = []
    for group_name in ERP_TEAM_ROLE_MATRIX:
        groups.append(
            seed_erp_team_role_group(Group, Permission, group_name, stdout=stdout)
        )
    return groups
