"""Shared free-text search for AdmittedStudent list/directory views."""
from __future__ import annotations

from functools import reduce
from operator import and_

from django.db.models import Q


def admitted_student_search_q(search: str) -> Q:
    """
    Q for filtering AdmittedStudent by a free-text search term, covering:

    - identity: student_id / reg_no / schoolpay_code (exact match, or prefix
      match once the term is at least 2 characters)
    - person name: each whitespace-separated word of the search term must
      match somewhere in first/middle/last name (in any field, any order —
      so "John Doe", "Doe John", and a middle-name-only search all work)
    - programme / faculty name
    - contact: phone / email

    Used by both the new-admission directory (ListAdmittedStudents) and the
    Bonafide students list (ListBonafideStudents) so the two stay consistent.
    """
    search = (search or "").strip()
    if not search:
        return Q(pk__isnull=True)

    identity = (
        Q(student_id__iexact=search)
        | Q(reg_no__iexact=search)
        | Q(schoolpay_code__iexact=search)
    )
    if len(search) >= 2:
        identity |= (
            Q(student_id__istartswith=search)
            | Q(reg_no__istartswith=search)
            | Q(schoolpay_code__istartswith=search)
        )

    words = search.split()
    per_word_name_q = [
        Q(application__first_name__icontains=word)
        | Q(application__middle_name__icontains=word)
        | Q(application__last_name__icontains=word)
        for word in words
    ]
    person_name_q = reduce(and_, per_word_name_q) if per_word_name_q else Q(pk__isnull=True)

    program_q = (
        Q(admitted_program__name__icontains=search)
        | Q(admitted_program__faculty__name__icontains=search)
    )
    contact_q = (
        Q(application__phone__icontains=search)
        | Q(application__email__icontains=search)
    )

    return identity | person_name_q | program_q | contact_q
