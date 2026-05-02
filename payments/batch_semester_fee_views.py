"""
NEW MODULE — Semester tuition management API (matrix GET/POST + bulk upload).

GET/POST  api/payments/batch_semester_fees/matrix
POST      api/payments/batch_semester_fees/bulk_upload

Reads/writes FeePlanRule rows for Programs.ProgramBatch × Programs.Semester
(tuition + functional amounts). See batch_semester_fee_helpers.py.
"""
from decimal import InvalidOperation

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.models import Program, ProgramBatch, Semester

from .batch_semester_fee_helpers import (
    functional_head,
    get_or_create_tuition_fee_plan,
    parse_decimal,
    plan_covers_program,
    rule_amount_map,
    tuition_head,
    upsert_rule,
)
from .feeplanrule_table import ensure_feeplanrule_table


class BatchSemesterFeeMatrixView(APIView):
    """
    NEW MODULE — Semester tuition matrix (one ProgramBatch, all semesters).

    GET: query program_id + program_batch_id → rows with tuition/functional amounts.
    POST: body program_id, program_batch_id, semester_id + amounts → upsert rules.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_feeplanrule_table()
        program_id = request.query_params.get('program_id')
        program_batch_id = request.query_params.get('program_batch_id')
        if not program_id or not program_batch_id:
            return Response(
                {'detail': 'program_id and program_batch_id are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            program = Program.objects.get(pk=int(program_id))
            program_batch = ProgramBatch.objects.get(pk=int(program_batch_id), program=program)
        except (Program.DoesNotExist, ProgramBatch.DoesNotExist):
            return Response({'detail': 'Program or program batch not found'}, status=status.HTTP_404_NOT_FOUND)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid id'}, status=status.HTTP_400_BAD_REQUEST)

        fee_plan = get_or_create_tuition_fee_plan(program)
        amounts = rule_amount_map(fee_plan.id, program.id, program_batch.id)
        rows = []
        for sem in program_batch.semesters.filter(is_active=True).order_by('order', 'start_date', 'id'):
            key = (program_batch.id, sem.id)
            cell = amounts.get(key, {})
            ti = cell.get('tuition_international')
            fi = cell.get('functional_international')
            rows.append(
                {
                    'program_batch_id': program_batch.id,
                    'program_batch_name': program_batch.name,
                    'semester_id': sem.id,
                    'semester_name': sem.name,
                    'order': sem.order,
                    'tuition_amount': str(cell.get('tuition') or '0'),
                    'functional_amount': str(cell.get('functional') or '0'),
                    'currency': cell.get('currency') or 'UGX',
                    'tuition_amount_international': str(ti) if ti is not None else '',
                    'tuition_currency_international': cell.get('tuition_currency_international') or '',
                    'functional_amount_international': str(fi) if fi is not None else '',
                    'functional_currency_international': cell.get('functional_currency_international') or '',
                }
            )

        return Response(
            {
                'fee_plan': {'id': fee_plan.id, 'name': fee_plan.name},
                'program': {'id': program.id, 'name': program.name, 'short_form': program.short_form},
                'program_batch': {
                    'id': program_batch.id,
                    'name': program_batch.name,
                    'academic_year': getattr(program_batch, 'academic_year', '') or '',
                },
                'rows': rows,
            }
        )

    def post(self, request):
        ensure_feeplanrule_table()
        tuition_head()
        functional_head()

        try:
            program = Program.objects.get(pk=int(request.data.get('program_id')))
            pb = ProgramBatch.objects.get(pk=int(request.data.get('program_batch_id')), program=program)
            sem = Semester.objects.get(pk=int(request.data.get('semester_id')), program_batch=pb)
        except (Program.DoesNotExist, ProgramBatch.DoesNotExist, Semester.DoesNotExist):
            return Response(
                {'detail': 'Invalid program, program batch or semester'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (TypeError, ValueError):
            return Response({'detail': 'Invalid ids'}, status=status.HTTP_400_BAD_REQUEST)

        fee_plan = get_or_create_tuition_fee_plan(program)
        if not plan_covers_program(fee_plan, program.id):
            return Response(
                {'detail': 'Fee plan could not be linked to this program'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        currency = (request.data.get('currency') or 'UGX').strip()[:3]
        currency_intl = (request.data.get('currency_international') or '').strip()[:3]
        try:
            tuition_amt = parse_decimal(request.data.get('tuition_amount'))
            func_amt = parse_decimal(request.data.get('functional_amount'))
            raw_ti = request.data.get('tuition_amount_international')
            raw_fi = request.data.get('functional_amount_international')
            tuition_intl = parse_decimal(raw_ti) if raw_ti not in (None, '') else None
            func_intl = parse_decimal(raw_fi) if raw_fi not in (None, '') else None
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)

        upsert_rule(
            fee_plan,
            program,
            pb,
            sem,
            tuition_head(),
            tuition_amt,
            currency,
            amount_international=tuition_intl if tuition_intl and tuition_intl > 0 else None,
            currency_international=currency_intl,
        )
        upsert_rule(
            fee_plan,
            program,
            pb,
            sem,
            functional_head(),
            func_amt,
            currency,
            amount_international=func_intl if func_intl and func_intl > 0 else None,
            currency_international=currency_intl,
        )

        return Response(
            {
                'message': 'Saved tuition and functional fees for this semester',
                'tuition_amount': str(tuition_amt),
                'functional_amount': str(func_amt),
                'currency': currency,
            },
            status=status.HTTP_200_OK,
        )


class BulkUploadSemesterTuitionView(APIView):
    """
    POST /api/payments/batch_semester_fees/bulk_upload

    Accepts:
      - multipart fields:  program_id, program_batch_id
      - multipart file:    file (CSV)

    CSV columns (header row required):
      semester_name*  tuition_amount*  functional_amount  currency
      tuition_amount_international  functional_amount_international  currency_international
    (* required)

    Matches semester_name (case-insensitive, stripped) against active semesters in
    the given program_batch.  Rows for unrecognised names are reported as errors.
    All valid rows are upserted (idempotent).

    Returns:
      {
        saved: <int>,
        error_count: <int>,
        errors: [{ row, semester_name, reason }],
      }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        import csv
        import io

        ensure_feeplanrule_table()

        # ── Validate program / batch ──────────────────────────────────────────
        try:
            program = Program.objects.get(pk=int(request.data.get('program_id') or 0))
            pb = ProgramBatch.objects.get(
                pk=int(request.data.get('program_batch_id') or 0),
                program=program,
            )
        except (Program.DoesNotExist, ProgramBatch.DoesNotExist, ValueError, TypeError):
            return Response(
                {'detail': 'Invalid program_id or program_batch_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Validate file ─────────────────────────────────────────────────────
        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response(
                {'detail': 'No file received. Send the CSV as multipart field "file".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not uploaded.name.lower().endswith('.csv'):
            return Response(
                {'detail': 'Only .csv files are accepted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            text = uploaded.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            return Response(
                {'detail': 'Could not decode file — ensure it is UTF-8 encoded.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return Response(
                {'detail': 'CSV file is empty or has no header row.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        headers = {h.strip().lower() for h in reader.fieldnames}
        if 'semester_name' not in headers or 'tuition_amount' not in headers:
            return Response(
                {'detail': 'CSV must have at least "semester_name" and "tuition_amount" columns.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Build semester lookup (name → Semester) ───────────────────────────
        semesters = pb.semesters.filter(is_active=True)
        sem_lookup = {s.name.strip().lower(): s for s in semesters}

        # ── Prepare fee plan + heads ──────────────────────────────────────────
        tuition_head()
        functional_head()
        fee_plan = get_or_create_tuition_fee_plan(program)
        if not plan_covers_program(fee_plan, program.id):
            return Response(
                {'detail': 'Fee plan could not be linked to this program.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        saved = 0
        errors = []

        for row_num, raw in enumerate(reader, start=2):
            row = {k.strip().lower(): (v or '').strip() for k, v in raw.items() if k}

            sem_name = row.get('semester_name', '')
            sem = sem_lookup.get(sem_name.lower())
            if not sem:
                errors.append({
                    'row': row_num,
                    'semester_name': sem_name,
                    'reason': (
                        f'Semester "{sem_name}" not found in this batch. '
                        f'Known: {", ".join(s.name for s in semesters)}'
                    ),
                })
                continue

            try:
                tuition_amt = parse_decimal(row.get('tuition_amount') or '0')
                func_amt = parse_decimal(row.get('functional_amount') or '0')
            except (InvalidOperation, TypeError, ValueError):
                errors.append({
                    'row': row_num,
                    'semester_name': sem_name,
                    'reason': 'tuition_amount or functional_amount is not a valid number.',
                })
                continue

            currency = (row.get('currency') or 'UGX').upper().strip()[:3]
            currency_intl = (row.get('currency_international') or '').upper().strip()[:3]

            raw_ti = row.get('tuition_amount_international') or ''
            raw_fi = row.get('functional_amount_international') or ''
            try:
                tuition_intl = parse_decimal(raw_ti) if raw_ti else None
                func_intl = parse_decimal(raw_fi) if raw_fi else None
            except (InvalidOperation, TypeError, ValueError):
                tuition_intl = None
                func_intl = None

            upsert_rule(
                fee_plan, program, pb, sem, tuition_head(),
                tuition_amt, currency,
                amount_international=tuition_intl if tuition_intl and tuition_intl > 0 else None,
                currency_international=currency_intl,
            )
            upsert_rule(
                fee_plan, program, pb, sem, functional_head(),
                func_amt, currency,
                amount_international=func_intl if func_intl and func_intl > 0 else None,
                currency_international=currency_intl,
            )
            saved += 1

        return Response(
            {
                'saved': saved,
                'error_count': len(errors),
                'errors': errors,
            },
            status=status.HTTP_200_OK,
        )
