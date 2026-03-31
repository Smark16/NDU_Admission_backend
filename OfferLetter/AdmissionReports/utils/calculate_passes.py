# calculate passes
PP_GRADES = ["A", "B", "C", "D", "E"]
ICT_SP_GRADES = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]

def calculate_pp_sp(alevel_results):
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
        if subject_name == "SUB" and grade in ICT_SP_GRADES:
            sp += 1
            continue
        if grade == "O":
            sp += 1
            continue

    return pp, sp