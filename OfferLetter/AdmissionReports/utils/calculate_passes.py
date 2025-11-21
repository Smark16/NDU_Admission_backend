# calculate passes
PP_GRADES = ["A", "B", "C", "D", "E"]
ICT_SP_GRADES = ["D1", "D2", "C3", "C4", "C5", "C6"]

def calculate_pp_sp(alevel_results):
    """
    alevel_results = list of dicts: [{"subject_name": "Physics", "grade": "A"}, ...]
    """
    pp = sp = 0

    for res in alevel_results:
        # Use .get() to be safe
        subject_name = res.get("subject_name", "").upper()
        grade = res.get("grade", "").upper()

        # Principal Pass
        if grade in PP_GRADES:
            pp += 1
            continue

        # Subsidiary Pass
        if subject_name == "ICT" and grade in ICT_SP_GRADES:
            sp += 1
            continue
        if subject_name == "GP" and grade in ICT_SP_GRADES:
            sp += 1
            continue
        if subject_name == "SUB MATH" and grade in ICT_SP_GRADES:
            sp += 1
            continue
        if grade == "O":
            sp += 1
            continue

    return pp, sp