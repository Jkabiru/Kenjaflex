"""Decision 2 – disputes table

Adds the disputes table for the Hunter-side refund flow. One row per
paid search; unique constraint on search_id prevents filing twice.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'disputes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hunter_id', sa.Integer(), nullable=False),
        sa.Column('search_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'resolved', name='disputestatus'),
            nullable=False,
            server_default='pending',
        ),
        sa.Column(
            'resolution',
            sa.Enum('refunded', 'denied', name='disputeresolution'),
            nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hunter_id'], ['users.id']),
        sa.ForeignKeyConstraint(['search_id'], ['searches.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('search_id', name='uq_dispute_search'),
    )


def downgrade() -> None:
    op.drop_table('disputes')
