"""Voice delivery features per report; old rows get an empty object."""

import sqlalchemy as sa

from alembic import op

revision = "0004_report_delivery_metrics"
down_revision = "0003_report_v2_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("session_reports") as batch:
        batch.add_column(
            sa.Column("delivery_metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("session_reports") as batch:
        batch.drop_column("delivery_metrics")
