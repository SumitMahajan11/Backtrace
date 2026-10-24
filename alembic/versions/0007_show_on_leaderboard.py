"""Add show_on_leaderboard column to users

Revision ID: 0007_show_on_leaderboard
Revises: 0006_is_showcase
Create Date: 2026-10-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007_show_on_leaderboard'
down_revision: Union[str, None] = '0006_is_showcase'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('users')]
    if 'show_on_leaderboard' not in columns:
        with op.batch_alter_table('users') as batch_op:
            batch_op.add_column(sa.Column('show_on_leaderboard', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('show_on_leaderboard')
