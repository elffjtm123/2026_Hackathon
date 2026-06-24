"""add scripts, style transfer jobs, and modular report metrics"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_scripts_and_modular_reports"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("practice_sessions", sa.Column("original_script", sa.Text()))
    op.add_column("practice_sessions", sa.Column("active_script", sa.Text()))
    op.add_column("practice_sessions", sa.Column("time_limit_seconds", sa.Integer()))
    op.add_column("practice_sessions", sa.Column("script_syllable_count", sa.Integer()))
    op.add_column("practice_sessions", sa.Column("target_syllables_per_minute", sa.Float()))

    op.add_column("session_reports", sa.Column("pronunciation_clarity_score", sa.Float()))
    op.add_column("session_reports", sa.Column("script_completion_ratio", sa.Float()))
    op.add_column("session_reports", sa.Column("time_adherence_score", sa.Float()))
    op.add_column(
        "session_reports", sa.Column("gaze_metrics", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "session_reports",
        sa.Column("speech_rate_metrics", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "session_reports",
        sa.Column("pronunciation_metrics", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "session_reports",
        sa.Column("script_sync_metrics", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "session_reports",
        sa.Column("scoring_version", sa.String(20), nullable=False, server_default="v1"),
    )

    op.create_table(
        "style_transfer_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_script", sa.Text(), nullable=False),
        sa.Column("result_script", sa.Text()),
        sa.Column("style_vector", sa.JSON(), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=False),
        sa.Column("estimated_duration_seconds", sa.Integer()),
        sa.Column("change_summary", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("safety_result", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_model", sa.String(100)),
        sa.Column("error_code", sa.String(80)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["practice_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_style_transfer_jobs_user_id", "style_transfer_jobs", ["user_id"])
    op.create_index("ix_style_transfer_jobs_session_id", "style_transfer_jobs", ["session_id"])
    op.create_index("ix_style_transfer_jobs_status", "style_transfer_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("style_transfer_jobs")
    for column in (
        "scoring_version",
        "script_sync_metrics",
        "pronunciation_metrics",
        "speech_rate_metrics",
        "gaze_metrics",
        "time_adherence_score",
        "script_completion_ratio",
        "pronunciation_clarity_score",
    ):
        op.drop_column("session_reports", column)
    for column in (
        "target_syllables_per_minute",
        "script_syllable_count",
        "time_limit_seconds",
        "active_script",
        "original_script",
    ):
        op.drop_column("practice_sessions", column)
