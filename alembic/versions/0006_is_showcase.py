"""Add is_showcase column to analysis_jobs

Revision ID: 0006_is_showcase
Revises: 0005_last_run_code
Create Date: 2026-10-20 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006_is_showcase'
down_revision: Union[str, None] = '0005_last_run_code'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('analysis_jobs')]
    if 'is_showcase' not in columns:
        with op.batch_alter_table('analysis_jobs') as batch_op:
            batch_op.add_column(sa.Column('is_showcase', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('analysis_jobs') as batch_op:
        batch_op.drop_column('is_showcase')
