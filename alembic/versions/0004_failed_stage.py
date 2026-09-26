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


def upgrade() -> None:
    with op.batch_alter_table('analysis_jobs') as batch_op:
        batch_op.add_column(sa.Column('failed_stage', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('analysis_jobs') as batch_op:
        batch_op.drop_column('failed_stage')
