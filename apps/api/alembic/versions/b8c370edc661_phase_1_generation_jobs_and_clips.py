"""phase 1: generation jobs and clips

Revision ID: b8c370edc661
Revises: 9a1f6d1d99c0
Create Date: 2026-05-03 07:21:43.195618

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8c370edc661'
down_revision: str | None = '9a1f6d1d99c0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'generation_jobs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('prompt', sqlmodel.sql.sqltypes.AutoString(length=4000), nullable=False),
        sa.Column('n_variants', sa.Integer(), nullable=False),
        sa.Column('aspect_ratio', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('model', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED', name='generationjobstatus'),
            nullable=False,
        ),
        sa.Column('best_clip_id', sa.Uuid(), nullable=True),
        sa.Column('error', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_generation_jobs_project_id'), 'generation_jobs', ['project_id'], unique=False)
    op.create_index(op.f('ix_generation_jobs_status'), 'generation_jobs', ['status'], unique=False)

    op.create_table(
        'clips',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('generation_job_id', sa.Uuid(), nullable=True),
        sa.Column('variant_index', sa.Integer(), nullable=False),
        sa.Column('prompt', sqlmodel.sql.sqltypes.AutoString(length=4000), nullable=False),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'GENERATING', 'DOWNLOADING', 'SCORING', 'SUCCEEDED', 'FAILED', name='clipstatus'),
            nullable=False,
        ),
        sa.Column('provider_job_id', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column('polling_url', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column('source_url', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column('storage_key', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column('public_url', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('score_explanation', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('error', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['generation_job_id'], ['generation_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_clips_generation_job_id'), 'clips', ['generation_job_id'], unique=False)
    op.create_index(op.f('ix_clips_project_id'), 'clips', ['project_id'], unique=False)
    op.create_index(op.f('ix_clips_status'), 'clips', ['status'], unique=False)

    op.create_foreign_key(
        'fk_generation_jobs_best_clip_id_clips',
        'generation_jobs',
        'clips',
        ['best_clip_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_generation_jobs_best_clip_id_clips',
        'generation_jobs',
        type_='foreignkey',
    )
    op.drop_index(op.f('ix_clips_status'), table_name='clips')
    op.drop_index(op.f('ix_clips_project_id'), table_name='clips')
    op.drop_index(op.f('ix_clips_generation_job_id'), table_name='clips')
    op.drop_table('clips')
    op.drop_index(op.f('ix_generation_jobs_status'), table_name='generation_jobs')
    op.drop_index(op.f('ix_generation_jobs_project_id'), table_name='generation_jobs')
    op.drop_table('generation_jobs')
