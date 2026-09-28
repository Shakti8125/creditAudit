"""Add RAG telemetry, feedback and evaluation tables

Revision ID: d4e5f6a7b8c9
Revises: c7d8e9f0a1b2
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRACE_MS = (
    'masking_ms', 'dense_ms', 'bm25_ms', 'fusion_ms', 'rerank_ms',
    'retrieval_ms', 'generation_ms', 'ttft_ms', 'total_ms',
)
_TRACE_COUNTS = (
    'dense_count', 'bm25_count', 'fused_count', 'reranked_count', 'citation_count', 'answer_citation_count',
)
_RUN_METRICS = (
    'hit_rate', 'mean_recall', 'mean_precision', 'mrr', 'mean_ndcg', 'mean_faithfulness',
    'mean_answer_relevance', 'mean_answer_correctness', 'p50_latency_ms', 'p95_latency_ms',
)


def upgrade() -> None:
    op.create_table(
        'rag_traces',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('endpoint', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('session_id', sa.Uuid(), nullable=True),
        sa.Column('chat_message_id', sa.Uuid(), nullable=True),
        sa.Column('document_id', sa.Uuid(), nullable=True),
        sa.Column('query_masked', sa.Text(), nullable=True),
        sa.Column('query_chars', sa.Integer(), nullable=False),
        sa.Column('answer_preview', sa.Text(), nullable=True),
        sa.Column('retrieval_mode', sa.String(length=24), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False),
        *[sa.Column(c, sa.Float(), nullable=True) for c in _TRACE_MS],
        *[sa.Column(c, sa.Integer(), nullable=False) for c in _TRACE_COUNTS],
        sa.Column('top_score', sa.Float(), nullable=True),
        sa.Column('mean_score', sa.Float(), nullable=True),
        sa.Column('top_score_norm', sa.Float(), nullable=True),
        sa.Column('score_kind', sa.String(length=24), nullable=True),
        sa.Column('scores_json', sa.JSON(), nullable=True),
        sa.Column('fused_scores_json', sa.JSON(), nullable=True),
        sa.Column('rerank_applied', sa.Boolean(), nullable=False),
        sa.Column('rerank_fallback', sa.Boolean(), nullable=False),
        sa.Column('dense_empty', sa.Boolean(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('llm_fallback_used', sa.Boolean(), nullable=False),
        sa.Column('llm_calls_json', sa.JSON(), nullable=True),
        sa.Column('est_prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('est_completion_tokens', sa.Integer(), nullable=True),
        sa.Column('groundedness', sa.Float(), nullable=True),
        sa.Column('guardrail_blocked', sa.Boolean(), nullable=False),
        sa.Column('guardrail_reason', sa.String(length=64), nullable=True),
        sa.Column('output_guardrail_reason', sa.String(length=64), nullable=True),
        sa.Column('error_type', sa.String(length=128), nullable=True),
        sa.Column('error_stage', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rag_traces_tenant_id'), 'rag_traces', ['tenant_id'])
    op.create_index(op.f('ix_rag_traces_user_id'), 'rag_traces', ['user_id'])
    op.create_index(op.f('ix_rag_traces_endpoint'), 'rag_traces', ['endpoint'])
    op.create_index(op.f('ix_rag_traces_created_at'), 'rag_traces', ['created_at'])
    op.create_index('ix_rag_traces_tenant_created', 'rag_traces', ['tenant_id', 'created_at'])

    op.create_table(
        'rag_feedback',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('trace_id', sa.Uuid(), nullable=False),
        sa.Column('chat_message_id', sa.Uuid(), nullable=True),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('comment_masked', sa.Text(), nullable=True),
        sa.Column('tags_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['trace_id'], ['rag_traces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trace_id', 'user_id', name='uq_rag_feedback_trace_user'),
    )
    op.create_index(op.f('ix_rag_feedback_tenant_id'), 'rag_feedback', ['tenant_id'])
    op.create_index(op.f('ix_rag_feedback_user_id'), 'rag_feedback', ['user_id'])
    op.create_index(op.f('ix_rag_feedback_trace_id'), 'rag_feedback', ['trace_id'])
    op.create_index(op.f('ix_rag_feedback_created_at'), 'rag_feedback', ['created_at'])

    op.create_table(
        'rag_eval_cases',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('reference_answer', sa.Text(), nullable=True),
        sa.Column('expected_refs_json', sa.JSON(), nullable=False),
        sa.Column('document_id', sa.Uuid(), nullable=True),
        sa.Column('origin', sa.String(length=16), nullable=False),
        sa.Column('default_key', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'default_key', name='uq_rag_eval_cases_tenant_default_key'),
    )
    op.create_index(op.f('ix_rag_eval_cases_tenant_id'), 'rag_eval_cases', ['tenant_id'])

    op.create_table(
        'rag_eval_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('group_id', sa.Uuid(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('mode', sa.String(length=24), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False),
        sa.Column('include_generation', sa.Boolean(), nullable=False),
        sa.Column('judge', sa.String(length=16), nullable=False),
        sa.Column('case_ids_json', sa.JSON(), nullable=False),
        sa.Column('total_cases', sa.Integer(), nullable=False),
        sa.Column('completed_cases', sa.Integer(), nullable=False),
        sa.Column('failed_cases', sa.Integer(), nullable=False),
        *[sa.Column(c, sa.Float(), nullable=True) for c in _RUN_METRICS],
        sa.Column('metrics_json', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rag_eval_runs_tenant_id'), 'rag_eval_runs', ['tenant_id'])
    op.create_index(op.f('ix_rag_eval_runs_user_id'), 'rag_eval_runs', ['user_id'])
    op.create_index(op.f('ix_rag_eval_runs_group_id'), 'rag_eval_runs', ['group_id'])
    op.create_index(op.f('ix_rag_eval_runs_status'), 'rag_eval_runs', ['status'])
    op.create_index('ix_rag_eval_runs_tenant_created', 'rag_eval_runs', ['tenant_id', 'created_at'])

    op.create_table(
        'rag_eval_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('case_id', sa.Uuid(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('question_masked', sa.Text(), nullable=True),
        sa.Column('document_id', sa.Uuid(), nullable=True),
        sa.Column('n_targets', sa.Integer(), nullable=False),
        sa.Column('targets_matched', sa.Integer(), nullable=False),
        sa.Column('hit', sa.Boolean(), nullable=True),
        sa.Column('first_relevant_rank', sa.Integer(), nullable=True),
        sa.Column('recall', sa.Float(), nullable=True),
        sa.Column('precision', sa.Float(), nullable=True),
        sa.Column('reciprocal_rank', sa.Float(), nullable=True),
        sa.Column('ndcg', sa.Float(), nullable=True),
        sa.Column('relevances_json', sa.JSON(), nullable=True),
        sa.Column('retrieved_json', sa.JSON(), nullable=True),
        sa.Column('answer_masked', sa.Text(), nullable=True),
        sa.Column('faithfulness', sa.Float(), nullable=True),
        sa.Column('answer_relevance', sa.Float(), nullable=True),
        sa.Column('answer_correctness', sa.Float(), nullable=True),
        sa.Column('judge_method', sa.String(length=16), nullable=False),
        sa.Column('judge_rationale', sa.Text(), nullable=True),
        sa.Column('retrieval_ms', sa.Float(), nullable=True),
        sa.Column('generation_ms', sa.Float(), nullable=True),
        sa.Column('judge_ms', sa.Float(), nullable=True),
        sa.Column('diagnostics_json', sa.JSON(), nullable=True),
        sa.Column('error_type', sa.String(length=128), nullable=True),
        sa.Column('error_stage', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['rag_eval_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rag_eval_results_run_id'), 'rag_eval_results', ['run_id'])
    op.create_index(op.f('ix_rag_eval_results_tenant_id'), 'rag_eval_results', ['tenant_id'])
    op.create_index(op.f('ix_rag_eval_results_case_id'), 'rag_eval_results', ['case_id'])


def downgrade() -> None:
    for name in ('ix_rag_eval_results_case_id', 'ix_rag_eval_results_tenant_id', 'ix_rag_eval_results_run_id'):
        op.drop_index(name, table_name='rag_eval_results')
    op.drop_table('rag_eval_results')
    for name in (
        'ix_rag_eval_runs_tenant_created', 'ix_rag_eval_runs_status', 'ix_rag_eval_runs_group_id',
        'ix_rag_eval_runs_user_id', 'ix_rag_eval_runs_tenant_id',
    ):
        op.drop_index(name, table_name='rag_eval_runs')
    op.drop_table('rag_eval_runs')
    op.drop_index('ix_rag_eval_cases_tenant_id', table_name='rag_eval_cases')
    op.drop_table('rag_eval_cases')
    for name in (
        'ix_rag_feedback_created_at', 'ix_rag_feedback_trace_id',
        'ix_rag_feedback_user_id', 'ix_rag_feedback_tenant_id',
    ):
        op.drop_index(name, table_name='rag_feedback')
    op.drop_table('rag_feedback')
    for name in (
        'ix_rag_traces_tenant_created', 'ix_rag_traces_created_at', 'ix_rag_traces_endpoint',
        'ix_rag_traces_user_id', 'ix_rag_traces_tenant_id',
    ):
        op.drop_index(name, table_name='rag_traces')
    op.drop_table('rag_traces')
