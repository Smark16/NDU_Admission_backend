"""
NEW MODULE — Safety net for FeePlanRule table.

If an old database was migrated without the FeePlanRule model, ensure_feeplanrule_table()
creates the table via the schema editor. Normal installs use migrations only.
"""
from django.db import OperationalError, connection

_feeplanrule_ready = False


def ensure_feeplanrule_table() -> None:
    """Create FeePlanRule table via schema editor if missing (SQLite/Postgres)."""
    global _feeplanrule_ready
    if _feeplanrule_ready:
        return
    from .models import FeePlanRule

    table = FeePlanRule._meta.db_table
    if table in connection.introspection.table_names():
        _feeplanrule_ready = True
        return
    try:
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(FeePlanRule)
    except OperationalError:
        if table in connection.introspection.table_names():
            _feeplanrule_ready = True
            return
        raise
    _feeplanrule_ready = True
