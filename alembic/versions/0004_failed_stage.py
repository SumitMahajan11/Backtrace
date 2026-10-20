"""Add failed_stage column to analysis_jobs

Revision ID: 0004_failed_stage
Revises: 0003_resolved_sha_and_repo_subpath
Create Date: 2026-09-25 07:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004_failed_stage'
down_revision: Union[str, None] = '0003_resolved_sha_repo_subpath'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Compatibility alias for database instances stamped with 0003_resolved_sha_and_repo_subpath
try:
    import alembic.script.revision as _alembic_rev
    _orig_resolve = _alembic_rev.RevisionMap._resolve_revision_number

    def _compat_resolve(self, id_):
        if id_ == '0003_resolved_sha_and_repo_subpath':
            id_ = '0003_resolved_sha_repo_subpath'
        return _orig_resolve(self, id_)

    _alembic_rev.RevisionMap._resolve_revision_number = _compat_resolve
except Exception:
    pass


def upgrade() -> None:
    bind = op.get_bind()
    try:
        bind.execute(sa.text("DELETE FROM alembic_version WHERE version_num = '0003_resolved_sha_and_repo_subpath'"))
    except Exception:
        pass
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('analysis_jobs')]
    if 'failed_stage' not in columns:
        with op.batch_alter_table('analysis_jobs') as batch_op:
            batch_op.add_column(sa.Column('failed_stage', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('analysis_jobs') as batch_op:
        batch_op.drop_column('failed_stage')
