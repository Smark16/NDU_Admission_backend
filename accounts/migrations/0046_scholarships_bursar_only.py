from django.db import migrations


def restrict_scholarships_to_bursar(apps, schema_editor):
    """Keep manage_scholarships on Bursar only; strip from other finance groups."""
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from accounts.erp_role_setup import seed_erp_team_role_group

    # Re-sync matrix for affected roles (removes manage_scholarships from non-Bursar).
    for name in ("Bursar", "Finance Manager", "Finance Officer"):
        seed_erp_team_role_group(Group, Permission, name)

    perm = (
        Permission.objects.filter(
            content_type__app_label="accounts",
            codename="manage_scholarships",
        ).first()
    )
    if not perm:
        return
    for group in Group.objects.exclude(name="Bursar").filter(permissions=perm):
        # Super Admin keeps all perms via its own seed; leave that group alone.
        if group.name == "Super Admin":
            continue
        group.permissions.remove(perm)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0045_hostel_module_initial"),
    ]

    operations = [
        migrations.RunPython(restrict_scholarships_to_bursar, noop_reverse),
    ]
