"""Add frontend compat columns

Revision ID: b39c1a2f3e4d
Revises: 0e6c2385a516
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b39c1a2f3e4d'
down_revision: Union[str, None] = '0e6c2385a516'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('models', sa.Column('portfolio', sa.String(), nullable=True))
    op.add_column('models', sa.Column('algorithm', sa.String(), nullable=True))
    op.add_column('regulatory_standards', sa.Column('effective_date', sa.String(), nullable=True))
    op.add_column('regulatory_standards', sa.Column('category', sa.String(), nullable=True))
    op.add_column('regulatory_standards', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('tenant_settings', sa.Column('min_observation_months', sa.Integer(), nullable=False, server_default='24'))


def downgrade() -> None:
    op.drop_column('tenant_settings', 'min_observation_months')
    op.drop_column('regulatory_standards', 'description')
    op.drop_column('regulatory_standards', 'category')
    op.drop_column('regulatory_standards', 'effective_date')
    op.drop_column('models', 'algorithm')
    op.drop_column('models', 'portfolio')