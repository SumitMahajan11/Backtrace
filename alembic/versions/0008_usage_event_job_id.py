"""Add job_id column to usage_events

Revision ID: 0008_usage_event_job_id
Revises: 0007_show_on_leaderboard
Create Date: 2026-10-24 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008_usage_event_job_id'
down_revision: Union[str, None] = '0007_show_on_leaderboard'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('usage_events')]
    if 'job_id' not in columns:
        with op.batch_alter_table('usage_events') as batch_op:
            batch_op.add_column(
                sa.Column('job_id', sa.Integer(), sa.ForeignKey('analysis_jobs.id', name='fk_usage_events_job_id', ondelete='CASCADE'), nullable=True)
            )
            batch_op.create_index('ix_usage_events_job_id', ['job_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('usage_events') as batch_op:
        batch_op.drop_index('ix_usage_events_job_id')
        batch_op.drop_column('job_id')
