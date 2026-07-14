def get_user_capabilities(user):
    return {
        "can_view_staff_dashboard": True,
        "can_view_team_appraisals": user.has_perm("hr.view_team_appraisals"),
        "can_view_all_appraisals": user.has_perm("hr.view_all_appraisals"),
        "can_manage_staff": user.has_perm("hr.manage_staff"),
    }
