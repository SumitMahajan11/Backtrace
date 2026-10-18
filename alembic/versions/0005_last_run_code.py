"""Add last_run_code column to milestone_attempts

Revision ID: 0005_last_run_code
Revises: 0004_failed_stage
Create Date: 2026-10-18 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005_last_run_code'
down_revision: Union[str, None] = '0004_failed_stage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('milestone_attempts')]
    if 'last_run_code' not in columns:
        with op.batch_alter_table('milestone_attempts') as batch_op:
            batch_op.add_column(sa.Column('last_run_code', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('milestone_attempts') as batch_op:
        batch_op.drop_column('last_run_code')
