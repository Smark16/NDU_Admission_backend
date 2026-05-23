import random
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model

from admissions.models import AdmittedStudent
from payments.models import TuitionLedger   # Change 'payments' if your app name is different

User = get_user_model()

class Command(BaseCommand):
    help = 'Populate TuitionLedger with 200 realistic dummy transactions (No Faker)'

    def handle(self, *args, **options):
        self.stdout.write("🚀 Starting to populate TuitionLedger...")

        # Get existing admitted students
        students = list(AdmittedStudent.objects.select_related('application').all()[:150])
        
        if not students:
            self.stdout.write(self.style.ERROR("❌ No AdmittedStudent records found. Please create some students first."))
            return

        users = list(User.objects.all()[:10])

        statuses = ["Completed", "Pending", "Failed", "Reversed"]
        sources = ["SchoolPay", "Bank Transfer", "MTN MoMo", "Airtel Money", "Portal Payment"]

        created_count = 0

        for i in range(200):
            student = random.choice(students)
            app = getattr(student, 'application', None)

            # Generate realistic data
            receipt_number = f"SP{random.randint(10000000, 99999999)}"
            trans_id = f"TXN{random.randint(100000000, 999999999)}"
            
            # Random date in last 6 months
            days_ago = random.randint(0, 180)
            payment_date = timezone.now() - timedelta(days=days_ago)

            amount = round(random.uniform(250000, 1850000), 2)   # Between 250k - 1.85M UGX

            status = random.choices(statuses, weights=[65, 20, 10, 5])[0]

            first_name = app.first_name if app and hasattr(app, 'first_name') else random.choice(["John", "Mary", "David", "Sarah", "Michael", "Grace", "Joseph", "Esther"])
            last_name = app.last_name if app and hasattr(app, 'last_name') else random.choice(["Mukasa", "Nabukenya", "Okello", "Nalubega", "Kato", "Nakato", "Ssempala"])

            TuitionLedger.objects.create(
                student=student,
                user=random.choice(users) if users and random.random() > 0.4 else None,
                
                amount=amount,
                payment_date_time=payment_date,
                
                schoolpay_receipt_number=receipt_number,
                settlement_bank_code=f"BK{random.randint(10, 99)}",
                source_channel_trans_detail="Payment received via SchoolPay platform",
                
                source_channel_transaction_id=trans_id,
                source_payment_channel=random.choice(sources),
                
                student_name=f"{first_name} {last_name}",
                student_payment_code=student.student_id or f"SP{student.id:06d}",
                student_registration_number=student.reg_no or f"REG{random.randint(10000, 99999)}",
                
                transaction_completion_status=status,
                
                raw_response={
                    "status": status.lower(),
                    "amount": str(amount),
                    "receipt_number": receipt_number,
                    "transaction_id": trans_id,
                    "payment_method": "SchoolPay"
                },
                
                reconciled=random.choice([True, False]),
            )

            created_count += 1

            if created_count % 50 == 0:
                self.stdout.write(f"✅ Created {created_count} records...")

        self.stdout.write(self.style.SUCCESS(f"\n🎉 Successfully created {created_count} TuitionLedger records!"))