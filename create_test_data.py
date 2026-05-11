import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ndu_portal.settings')
django.setup()

from datetime import date, timedelta
from accounts.models import User, Campus
from admissions.models import (
    Batch, AcademicLevel, Program, Application,
    OLevelSubject, ALevelSubject, OLevelResult, ALevelResult
)

campus = Campus.objects.first()
level  = AcademicLevel.objects.filter(name='Undergraduate').first()

admin_user = User.objects.get(email='admin@gmail.com')
batch, created_batch = Batch.objects.get_or_create(
    name='August Intake 2025',
    defaults={
        'academic_year': '2025/2026',
        'code': 'AUG2025',
        'is_active': True,
        'application_start_date': date.today() - timedelta(days=30),
        'application_end_date':   date.today() + timedelta(days=60),
        'admission_start_date':   date.today() - timedelta(days=10),
        'admission_end_date':     date.today() + timedelta(days=90),
        'created_by': admin_user,
    }
)
print('Batch:', batch.name, '(new)' if created_batch else '(exists)')

programs        = list(Program.objects.filter(is_active=True)[:4])
olevel_subjects = list(OLevelSubject.objects.all()[:6])
alevel_subjects = list(ALevelSubject.objects.all()[:3])

APPLICANTS = [
    dict(first='Alice',   last='Nakato',     email='alice.nakato@gmail.com',    gender='Female', nat='Ugandan', status='submitted'),
    dict(first='Brian',   last='Okello',     email='brian.okello@gmail.com',     gender='Male',   nat='Ugandan', status='submitted'),
    dict(first='Carol',   last='Atim',       email='carol.atim@gmail.com',       gender='Female', nat='Ugandan', status='accepted'),
    dict(first='David',   last='Ssempa',     email='david.ssempa@gmail.com',     gender='Male',   nat='Ugandan', status='accepted'),
    dict(first='Eva',     last='Mutesi',     email='eva.mutesi@gmail.com',       gender='Female', nat='Rwandan', status='rejected'),
    dict(first='Frank',   last='Opio',       email='frank.opio@gmail.com',       gender='Male',   nat='Ugandan', status='submitted'),
    dict(first='Grace',   last='Achen',      email='grace.achen@gmail.com',      gender='Female', nat='Ugandan', status='submitted'),
    dict(first='Henry',   last='Tumwine',    email='henry.tumwine@gmail.com',    gender='Male',   nat='Ugandan', status='accepted'),
    dict(first='Irene',   last='Nambi',      email='irene.nambi@gmail.com',      gender='Female', nat='Kenyan',  status='submitted'),
    dict(first='James',   last='Byaruhanga', email='james.bya@gmail.com',        gender='Male',   nat='Ugandan', status='rejected'),
    dict(first='Karen',   last='Akello',     email='karen.akello@gmail.com',     gender='Female', nat='Ugandan', status='submitted'),
    dict(first='Lawrence', last='Mutebi',    email='lawrence.mutebi@gmail.com',  gender='Male',   nat='Ugandan', status='submitted'),
]

GRADES_O = ['D1', 'D2', 'C3', 'C4', 'C5', 'C6']
GRADES_A = ['A',  'B',  'C',  'D',  'E']

created_count = 0
for i, d in enumerate(APPLICANTS):
    user, _ = User.objects.get_or_create(
        email=d['email'],
        defaults=dict(
            username=d['email'],
            first_name=d['first'],
            last_name=d['last'],
            is_applicant=True,
            is_active=True,
        )
    )
    if _:
        user.set_password('Test@1234')
        user.save()

    if Application.objects.filter(applicant=user, batch=batch).exists():
        print('  skip: ' + d['first'] + ' ' + d['last'] + ' (already exists)')
        continue

    app = Application.objects.create(
        applicant=user,
        batch=batch,
        campus=campus,
        academic_level=level,
        first_name=d['first'],
        last_name=d['last'],
        email=d['email'],
        phone='+25670' + str(700 + i).zfill(7),
        gender=d['gender'],
        nationality=d['nat'],
        date_of_birth=date(2000 + i % 5, (i % 12) + 1, (i % 28) + 1),
        address='Kampala, Uganda',
        olevel_school="St. Mary's College Kisubi",
        olevel_year=2018 + i % 3,
        alevel_school='Makerere College School',
        alevel_year=2020 + i % 2,
        alevel_combination='PCM',
        status=d['status'],
        application_fee_paid=True,
    )

    prog_slice = programs[i % len(programs): i % len(programs) + 2]
    if not prog_slice:
        prog_slice = programs[:1]
    app.programs.set(prog_slice)

    for j, subj in enumerate(olevel_subjects[:5]):
        OLevelResult.objects.create(application=app, subject=subj, grade=GRADES_O[(i + j) % len(GRADES_O)])

    for j, subj in enumerate(alevel_subjects[:3]):
        ALevelResult.objects.create(application=app, subject=subj, grade=GRADES_A[(i + j) % len(GRADES_A)])

    created_count += 1
    print('  Created: ' + d['first'] + ' ' + d['last'] + ' (' + d['status'] + ')')

print('')
print('Done — ' + str(created_count) + ' applications created')
print('Batch: ' + batch.name + ' (' + batch.academic_year + ')')
print('Submitted: ' + str(Application.objects.filter(batch=batch, status='submitted').count()))
print('Accepted:  ' + str(Application.objects.filter(batch=batch, status='accepted').count()))
print('Rejected:  ' + str(Application.objects.filter(batch=batch, status='rejected').count()))
