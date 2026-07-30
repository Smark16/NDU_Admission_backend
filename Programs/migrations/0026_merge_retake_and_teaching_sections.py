# Merge retake branch (0021) with teaching-section branch (0025)
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("Programs", "0021_retake_missed_paper_registration"),
        ("Programs", "0025_courseunitsectionlecturer"),
    ]

    operations = []
