"""Add population deciles column

Revision ID: c7d8e9f0a1b2
Revises: b39c1a2f3e4d
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, None] = 'b39c1a2f3e4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('model_versions', sa.Column('population_deciles', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('model_versions', 'population_deciles')