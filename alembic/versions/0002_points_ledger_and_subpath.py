"""Add points_ledger table and analysis_jobs subpath/commit_ref columns

Revision ID: 0002_points_ledger_and_subpath
Revises: 0001_initial_postgres_schema
Create Date: 2026-09-24 11:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_points_ledger_and_subpath'
down_revision: Union[str, None] = '0001_initial_postgres_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add commit_ref and subpath to analysis_jobs
    with op.batch_alter_table('analysis_jobs') as batch_op:
        batch_op.add_column(sa.Column('commit_ref', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('subpath', sa.String(length=500), nullable=True))

    # 2. Create points_ledger table
    op.create_table(
        'points_ledger',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('milestone_tier', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('points_awarded', sa.Integer(), nullable=False),
        sa.Column('multiplier_applied', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('reason', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_points_user_created', 'points_ledger', ['user_id', 'created_at'], unique=False)
    op.create_index('idx_points_user_job_tier', 'points_ledger', ['user_id', 'job_id', 'milestone_tier'], unique=False)
    op.create_index(op.f('ix_points_ledger_created_at'), 'points_ledger', ['created_at'], unique=False)
    op.create_index(op.f('ix_points_ledger_job_id'), 'points_ledger', ['job_id'], unique=False)
    op.create_index(op.f('ix_points_ledger_milestone_tier'), 'points_ledger', ['milestone_tier'], unique=False)
    op.create_index(op.f('ix_points_ledger_user_id'), 'points_ledger', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('points_ledger')
    with op.batch_alter_table('analysis_jobs') as batch_op:
        batch_op.drop_column('subpath')
        batch_op.drop_column('commit_ref')
