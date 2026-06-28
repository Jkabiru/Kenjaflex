"""Decision 3 – search event logging columns

Extends the searches table with unit_type and estate so analytics queries
can aggregate by what hunters are actually searching for, without parsing
the params_json blob. match_count and payment_status already cover
results_count and paid; created_at already covers hour-of-day.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('searches') as batch_op:
        batch_op.add_column(
            sa.Column(
                'unit_type',
                sa.Enum(
                    'bedsitter', 'studio', 'one_br', 'two_br', 'three_br', 'hostel_room',
                    name='unittype',
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column('estate', sa.String(length=255), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('searches') as batch_op:
        batch_op.drop_column('estate')
        batch_op.drop_column('unit_type')
