"""Initial PostgreSQL Schema Migration

Revision ID: 0001_initial_postgres_schema
Revises: 
Create Date: 2026-09-18 14:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_initial_postgres_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. repos table
    op.create_table(
        'repos',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('github_url', sa.String(length=255), nullable=False),
        sa.Column('commit_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('keep_longer', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('consent_prompt_improvement', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('consent_future_training', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_repo_url_commit', 'repos', ['github_url', 'commit_hash'], unique=False)
    op.create_index(op.f('ix_repos_commit_hash'), 'repos', ['commit_hash'], unique=False)
    op.create_index(op.f('ix_repos_expires_at'), 'repos', ['expires_at'], unique=False)
    op.create_index(op.f('ix_repos_github_url'), 'repos', ['github_url'], unique=False)

    # 2. ingestion_results table
    op.create_table(
        'ingestion_results',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('file_tree_json', sa.Text(), nullable=False),
        sa.Column('file_contents_json', sa.Text(), nullable=False),
        sa.Column('skipped_files_json', sa.Text(), nullable=False),
        sa.Column('redaction_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('clone_duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repo_id')
    )

    # 3. analysis_results table
    op.create_table(
        'analysis_results',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('pipeline_result_json', sa.Text(), nullable=False),
        sa.Column('execution_time_seconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repo_id')
    )

    # 4. users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('github_id', sa.Integer(), nullable=False),
        sa.Column('github_username', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)
    op.create_index(op.f('ix_users_github_id'), 'users', ['github_id'], unique=True)

    # 5. refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_tokens_expires_at'), 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)

    # 6. subscriptions table
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=False),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='inactive'),
        sa.Column('current_period_end', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_subscriptions_stripe_customer_id'), 'subscriptions', ['stripe_customer_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_stripe_subscription_id'), 'subscriptions', ['stripe_subscription_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=True)

    # 7. usage_events table
    op.create_table(
        'usage_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False, server_default='repo_analysis'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_events_created_at'), 'usage_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_usage_events_user_id'), 'usage_events', ['user_id'], unique=False)

    # 8. processed_webhook_events table
    op.create_table(
        'processed_webhook_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_processed_webhook_events_event_id'), 'processed_webhook_events', ['event_id'], unique=True)

    # 9. analysis_jobs table
    op.create_table(
        'analysis_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('repo_name', sa.String(length=255), nullable=False),
        sa.Column('github_url', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('execution_time_seconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('markdown_output', sa.Text(), nullable=False, server_default=''),
        sa.Column('graph_output_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('quiz_output_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_analysis_jobs_repo_name'), 'analysis_jobs', ['repo_name'], unique=False)
    op.create_index(op.f('ix_analysis_jobs_run_id'), 'analysis_jobs', ['run_id'], unique=False)
    op.create_index(op.f('ix_analysis_jobs_user_id'), 'analysis_jobs', ['user_id'], unique=False)

    # 10. milestone_attempts table
    op.create_table(
        'milestone_attempts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('milestone_tier', sa.Integer(), nullable=False),
        sa.Column('submitted_code', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='not_started'),
        sa.Column('hint_level_revealed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('implementation_revealed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('last_run_stdout', sa.Text(), nullable=True),
        sa.Column('last_run_stderr', sa.Text(), nullable=True),
        sa.Column('last_run_exit_code', sa.Integer(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('grading_method', sa.String(length=32), nullable=False, server_default='structural_only'),
        sa.Column('grading_details_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'job_id', 'milestone_tier', name='uq_user_job_milestone_tier')
    )
    op.create_index('idx_attempt_user_job_tier', 'milestone_attempts', ['user_id', 'job_id', 'milestone_tier'], unique=False)
    op.create_index(op.f('ix_milestone_attempts_job_id'), 'milestone_attempts', ['job_id'], unique=False)
    op.create_index(op.f('ix_milestone_attempts_milestone_tier'), 'milestone_attempts', ['milestone_tier'], unique=False)
    op.create_index(op.f('ix_milestone_attempts_user_id'), 'milestone_attempts', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('milestone_attempts')
    op.drop_table('analysis_jobs')
    op.drop_table('processed_webhook_events')
    op.drop_table('usage_events')
    op.drop_table('subscriptions')
    op.drop_table('refresh_tokens')
    op.drop_table('users')
    op.drop_table('analysis_results')
    op.drop_table('ingestion_results')
    op.drop_table('repos')
