"""Add resolved_sha to analysis_jobs and subpath to repos

Revision ID: 0003_resolved_sha_and_repo_subpath
Revises: 0002_points_ledger_and_subpath
Create Date: 2026-09-24 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003_resolved_sha_repo_subpath'
down_revision: Union[str, None] = '0002_points_ledger_and_subpath'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add resolved_sha to analysis_jobs
    with op.batch_alter_table('analysis_jobs') as batch_op:
        batch_op.add_column(sa.Column('resolved_sha', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_analysis_jobs_resolved_sha', ['resolved_sha'], unique=False)

    # 2. Add subpath to repos and composite index
    with op.batch_alter_table('repos') as batch_op:
        batch_op.add_column(sa.Column('subpath', sa.String(length=500), nullable=True))
        batch_op.create_index('idx_repo_url_commit_subpath', ['github_url', 'commit_hash', 'subpath'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('repos') as batch_op:
        batch_op.drop_index('idx_repo_url_commit_subpath')
        batch_op.drop_column('subpath')

    with op.batch_alter_table('analysis_jobs') as batch_op:
        batch_op.drop_index('ix_analysis_jobs_resolved_sha')
        batch_op.drop_column('resolved_sha')
