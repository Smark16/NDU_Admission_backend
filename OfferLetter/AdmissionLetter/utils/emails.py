from ndu_portal.send_grid import send_configurable_email

def offerletter_email(applicant_local, subject = "Admission letter sent successfully" ):
    body = (
            f"Dear {applicant_local.first_name} {applicant_local.last_name},\n\n"
            f"CONGRATULATIONS!\n\n"
            f"We are delighted to inform you that your admission letter has been **successfully sent to your portal**.\n\n"
            f"Next Steps:\n"
            f"1. Log in to your portal to download your official admission letter\n"
            f"2. Confirm everything is ok and sign where necessary\n"
            f"3. Complete registration before the deadline\n\n"
            f"We look forward to welcoming you to the Ndejje University family!\n\n"
            f"Warm regards,\n"
            f"Admissions Office\n"
            f"Ndejje University\n"
            f"Email: admissions@ndejjeuniversity.ac.ug\n"
            f"Website: www.ndejjeuniversity.ac.ug"
        )
    return send_configurable_email(applicant_local.email, subject, body)