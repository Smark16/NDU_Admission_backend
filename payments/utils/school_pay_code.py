import hashlib
import requests
from django.conf import settings
from urllib.parse import quote

def generate_request_hash(schoolCode, reg_no, password):
    raw = f"{schoolCode}{reg_no}{password}"
    # return hashlib.md5(raw.encode()).hexdigest().upper()
    return hashlib.md5(raw.encode('utf-8')).hexdigest().lower()

def register_student_with_schoolpay(admitted_student):
   
    schoolCode = settings.SCHOOL_PAY_CODE
    password = settings.SCHOOL_PAY_PASSWORD

    externalStudentCode = str(admitted_student.reg_no).strip()  # ✅ CORRECT FIELD
    encoded_reg_no = quote(externalStudentCode, safe="")  # 🔥 THIS FIXES EVERYTHING

    requestHash = generate_request_hash(schoolCode, externalStudentCode, password)

    url = f"https://schoolpaytest.servicecops.com/uatpaymentapi/AndroidRS/SyncSchoolStudent/{schoolCode}/{externalStudentCode}/{requestHash}"
    
    print("FINAL URL:", url)

    app = admitted_student.application  # ✅ get application data

    payload = {
        "firstName": app.first_name,
        "middleName": app.middle_name or "",
        "lastName": app.last_name,
        "classCode": admitted_student.admitted_batch.name if admitted_student.admitted_batch else "Y1",
        "guardianPhone": app.phone,
        "gender": app.gender,
        "dateOfBirth": str(app.date_of_birth) if app.date_of_birth else ""
    }

    try:
        response = requests.post(url, json=payload, timeout=30,  headers={"Content-Type": "application/json"})

        # print('schoolpay response', response)

        print("FINAL URL:", url)
        print("STATUS CODE:", response.status_code)
        print("CONTENT-TYPE:", response.headers.get('Content-Type'))
        print("RAW RESPONSE (first 800 chars):")
        print(response.text)   # <--- This is very important
        # print("STATUS:", response.status_code)
        # print("RAW RESPONSE:", response.text)  # 👈 VERY IMPORTANT
        try:
            data = response.json()
        except Exception:
            return {
                "success": False,
                "error": "Invalid JSON response from SchoolPay",
                "raw": response.text
            }

        # data = response.json()

        # 🔥 SAVE SCHOOLPAY CODE HERE
        if data.get("returnCode") == 0:
            admitted_student.student_id = data.get("studentCode")  # ✅ THIS IS YOUR PAYCODE
            admitted_student.is_registered_with_schoolpay = True
            admitted_student.save(update_fields=["student_id", "is_registered_with_schoolpay"])

        return {
            "success": data.get("returnCode") == 0,
            "data": data
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

