"""Nullable observations and persistent completion status; retain historical rows."""

import sqlalchemy as sa

from alembic import op

revision = "0003_report_v2_integrity"
down_revision = "0002_scripts_and_modular_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("session_reports") as batch:
        for name in (
            "overall_score",
            "gaze_score",
            "speech_rate_score",
            "filler_word_score",
            "average_syllables_per_minute",
        ):
            batch.alter_column(name, existing_type=sa.Float(), nullable=True)
        batch.alter_column("filler_word_counts", existing_type=sa.JSON(), nullable=True)
        batch.add_column(
            sa.Column("incomplete", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    # A downgrade cannot safely invent scores for v2 NULLs.
    raise RuntimeError(
        "Report v2 downgrade would discard unavailable observations; restore a backup instead."
    )
