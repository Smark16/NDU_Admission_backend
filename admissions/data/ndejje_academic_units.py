"""Official Ndejje University faculties and departments (ERP seed).

Source: Academic Registrar list received 14 Aug 2026.
"""

NDEJJE_ACADEMIC_UNITS = [
    {
        "code": "FBAM",
        "name": "Faculty of Business Administration & Management",
        "departments": [
            {"code": "ACCFIN", "name": "Accounting and Finance"},
            {"code": "MGECON", "name": "Management and Economics"},
        ],
    },
    {
        "code": "FSC",
        "name": "Faculty of Science & Computing",
        "departments": [
            {"code": "COMP", "name": "Department of Computing"},
            {"code": "SCI", "name": "Department of Science"},
            {"code": "SPORT", "name": "Department of Sports Science"},
        ],
    },
    {
        "code": "FEH",
        "name": "Faculty of Education & Humanities",
        "departments": [
            {"code": "EDUC", "name": "Department of Education"},
            {"code": "COMLANG", "name": "Department of Communication and Languages"},
            {"code": "REL", "name": "Department of Religious Studies"},
            {"code": "SOCSCI", "name": "Department of Social Sciences"},
            {"code": "HEC", "name": "Higher Education Certificate (HEC)"},
            {"code": "AFFIL", "name": "Affiliations"},
        ],
    },
    {
        "code": "FHS",
        "name": "Faculty of Health Sciences",
        "departments": [
            {
                "code": "CMCH",
                "name": "Department of Clinical Medicine and Community Health",
            },
        ],
    },
    {
        "code": "FENG",
        "name": "Faculty of Engineering",
        "departments": [
            {"code": "CIV", "name": "Department of Civil Engineering"},
            {"code": "GEO", "name": "Department of Geomatics"},
            {"code": "ELEC", "name": "Department of Electrical Engineering"},
            {"code": "MECH", "name": "Department of Mechanical Engineering"},
        ],
    },
    {
        "code": "FEAS",
        "name": "Faculty of Environment & Agricultural Sciences",
        "departments": [
            {"code": "AGRI", "name": "Department of Agriculture"},
            {"code": "ENV", "name": "Department of Environment"},
        ],
    },
]
