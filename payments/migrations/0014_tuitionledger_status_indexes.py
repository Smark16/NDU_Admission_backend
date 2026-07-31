# Speed up commitment/tuition-pct correlated-subquery checks against
# TuitionLedger. transaction_completion_status had no index at all, so
# every per-student EXISTS() check (bursar weekly report, bonafide
# strict commitment filter, etc.) could fall back to scanning the whole
# ledger table once per admitted student — catastrophically slow once
# a cohort has thousands of admitted students.
#
# On Postgres this uses CREATE INDEX CONCURRENTLY so it does not lock
# payments_tuitionledger while it builds (this table gets live writes
# from payment processing). Concurrent index creation cannot run inside
# a transaction, hence atomic = False. Falls back to a plain CREATE INDEX
# on non-Postgres backends (e.g. local SQLite dev, which has no
# concept of CONCURRENTLY and no meaningful lock contention anyway).

from django.db import migrations, models


def _create_indexes(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    concurrently = "CONCURRENTLY " if vendor == "postgresql" else ""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'CREATE INDEX {concurrently}IF NOT EXISTS "tl_status_student_idx" '
            'ON "payments_tuitionledger" ("transaction_completion_status", "student_id");'
        )
        cursor.execute(
            f'CREATE INDEX {concurrently}IF NOT EXISTS "tl_status_paycode_idx" '
            'ON "payments_tuitionledger" ("transaction_completion_status", "student_payment_code");'
        )


def _drop_indexes(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    concurrently = "CONCURRENTLY " if vendor == "postgresql" else ""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'DROP INDEX {concurrently}IF EXISTS "tl_status_student_idx";')
        cursor.execute(f'DROP INDEX {concurrently}IF EXISTS "tl_status_paycode_idx";')


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("payments", "0013_bursar_weekly_report_batch"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="tuitionledger",
                    index=models.Index(
                        fields=["transaction_completion_status", "student_id"],
                        name="tl_status_student_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="tuitionledger",
                    index=models.Index(
                        fields=["transaction_completion_status", "student_payment_code"],
                        name="tl_status_paycode_idx",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(_create_indexes, _drop_indexes),
            ],
        ),
    ]
