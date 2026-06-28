"""Decision 1 – field agent KYC enum

Replaces the boolean is_student_verified with a three-state
agent_verification_status enum (pending / verified / rejected) and adds
agent_verification_rejection_reason so admins can explain rejections.

Revision ID: a2b3c4d5e6f7
Revises: 50655cfb3564
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = '50655cfb3564'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table keeps SQLite happy (it can't ALTER columns directly).
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column(
                'agent_verification_status',
                sa.Enum('pending', 'verified', 'rejected', name='agentverificationstatus'),
                nullable=False,
                server_default='pending',
            )
        )
        batch_op.add_column(
            sa.Column('agent_verification_rejection_reason', sa.Text(), nullable=True)
        )
        batch_op.drop_column('is_student_verified')


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column('is_student_verified', sa.Boolean(), nullable=False, server_default='0')
        )
        batch_op.drop_column('agent_verification_rejection_reason')
        batch_op.drop_column('agent_verification_status')
