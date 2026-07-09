# hr/roles.py
def setup_roles(sender, **kwargs):
    from django.contrib.auth.models import Group, Permission
    roles = {
        "Staff": [
            # Appraisals (self)
            "appraisal.view_appraisal",

            # Leave (self-service)
            "staff.request_leave",
            "leave.add_leaverequest",

            # Profile & contract
            "staff.view_staffprofile",
            "staff.change_staffprofile",
            "staff.view_staffcontract",
        ],

        "Supervisor": [
            # ---- inherit Staff ----
            "staff.request_leave",
            "appraisal.view_appraisal",
            "leave.add_leaverequest",
            "staff.view_staffprofile",
            "staff.change_staffprofile",
            "staff.view_staffcontract",

            # ---- supervisor-specific ---
            "staff.view_team_appraisals",
            "staff.view_supervisedstaff",
            "staff.view_supervisionassignment",
            "staff.view_departmentteams",
            "staff.view_staffprofile",
        ],

        "HR": [
            # ---- Staff + Supervisor ----
            "staff.request_leave",
            "appraisal.view_appraisal",
            "leave.add_leaverequest",
            "leave.view_leaverequest",
            "leave.change_leaverequest",
            "staff.view_staffprofile",
            "staff.change_staffprofile",
            "staff.view_staffcontract",
            "hiring.view_jobopening",
            "hiring.add_jobapplication",
            "staff.view_team_appraisals",
            "staff.view_supervisionassignment",
            "staff.view_departmentteams",
            "staff.view_bulkuploadstaff",

            # ---- Staff management ----
            "staff.manage_staff",
            "staff.add_staffprofile",
            "staff.change_staffprofile",
            "staff.delete_staffprofile",
            "staff.view_stafftype",
            "staff.add_stafftype",
            "staff.change_stafftype",
            "staff.delete_stafftype",
            "staff.add_staffcontract",
            "staff.view_staffcontract",
            "staff.change_staffcontract",
            "staff.delete_staffcontract",

            # ---- Org structure ----
            "staff.add_department",
            "staff.view_department",
            "staff.change_department",
            "staff.delete_department",
            "staff.add_departmentteams",
            "staff.change_departmentteams",
            "staff.delete_departmentteams",
            "staff.view_stafftype",
            "staff.add_stafftype", 
            "staff.change_stafftype",
            "staff.delete_stafftype",
            "staff.view_positonlevel",
            "staff.add_positonlevel",
            "staff.change_positonlevel",
            "staff.delete_positonlevel",
            "accounts.view_campus",
            "accounts.add_campus",
            "accounts.delete_campus",
            "accounts.change_campus",

            # ---- Supervision ----
            "staff.add_supervisionassignment",
            "staff.change_supervisionassignment",
            "staff.delete_supervisionassignment",

            # ---- Hiring ----
            "hiring.add_jobopening",
            "hiring.view_jobopening",
            "hiring.change_jobopening",
            "hiring.delete_jobopening",
            "hiring.view_jobapplication",
            "hiring.change_jobapplication",
            "hiring.delete_jobapplication",
            "hiring.view_interview",
            "hiring.add_interview",
            "hiring.change_interview",
            "hiring.delete_interview",
            "hiring.add_employment",
            "hiring.change_employment",
            "hiring.delete_employment",

            # ---- Appraisal system ----
            "staff.view_all_appraisals",
            "appraisal.add_appraisal",
            "appraisal.change_appraisal",
            "appraisal.delete_appraisal",
            "appraisal.view_appraisalcycle",
            "appraisal.add_appraisalcycle",
            "appraisal.change_appraisalcycle",
            "appraisal.delete_appraisalcycle",
            "appraisal.view_strategicobjective",
            "staff.view_pips",

            # ---- Leave system (policies & approvals) ----
            "leave.view_leavetype",
            "leave.add_leavetype",
            "leave.delete_leavetype",
            "leave.change_leavetype",
            "leave.add_leavepolicy",
            "leave.change_leavepolicy",
            "leave.delete_leavepolicy",
            "leave.view_leavepolicy",
            "leave.add_leaveapproval",
            "leave.change_leaveapproval",
            "leave.delete_leaveapproval",
            "leave.add_leavebalance",
            "leave.change_leavebalance",
            "leave.delete_leavebalance",
            "leave.add_publicholiday",
            "leave.change_publicholiday",
            "leave.delete_publicholiday",

            # ---- System & permissions ----
            "auth.add_group",
            "auth.change_group",
            "auth.delete_group",
            "auth.add_permission",
            "auth.change_permission",
            "auth.delete_permission",
            "staff.add_systempermissions",
            "staff.change_systempermissions",
            "staff.delete_systempermissions",
            "staff.view_systempermissions",
            "accounts.view_user",
            "accounts.add_user",
            "accounts.delete_user",
            "accounts.change_user",
        ],
        }
    
    for role_name, perms in roles.items():
        group, _ = Group.objects.get_or_create(name=role_name)
        group.permissions.clear()  # optional but recommended

        for perm in perms:
            try:
                app_label, codename = perm.split(".")
                permission = Permission.objects.get(
                    codename=codename,
                    content_type__app_label=app_label
                )
                group.permissions.add(permission)
            except Permission.DoesNotExist:
                pass  # Some HR perms appear after later app migrations; run seed_hr_roles if needed.
