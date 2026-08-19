from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0017_scholarship_sponsor_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExemptionFormFeePayment",
            fields=[],
            options={
                "verbose_name": "Exemption form fee payment",
                "verbose_name_plural": "Exemption form fee payments",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("payments.studenttuitionpayment",),
        ),
    ]
