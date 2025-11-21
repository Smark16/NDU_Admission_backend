from datetime import date

def get_current_academic_year():
    today = date.today()
    year = today.year

    # if current month is August (8) or later → new academic year starts
    if today.month >= 8:
        start_year = year
        end_year = year + 1
    else:
        start_year = year - 1
        end_year = year

    return f"{start_year}/{end_year}"