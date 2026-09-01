from __future__ import annotations

from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPayload,
    TokenResponse,
)
from app.schemas.compare import (
    CompareRequest,
    CompareResponse,
    ComparisonDifference,
)
from app.schemas.document import (
    DocumentListResponse,
    DocumentMetadata,
    UploadResponse,
)
from app.schemas.gap_analysis import (
    ComplianceGap,
    GapAnalysisRequest,
    GapAnalysisResponse,
)
from app.schemas.metrics import (
    AnalyticsResponse,
    BreachReport,
    EWSReport,
    EWSSignal,
    MetricValue,
    ModelValidationProfile,
    PolicyResult,
)
from app.schemas.models import (
    ModelCreate,
    ModelExportData,
    ModelSummary,
    ModelVersionDTO,
)
from app.schemas.privacy import (
    MaskRequest,
    MaskResponse,
    RedactionLogResponse,
)
from app.schemas.query import (
    QueryRequest,
    QueryResponse,
)
from app.schemas.regulatory import (
    RegulatoryQuery,
    RegulatoryResponse,
    RegulatoryStandardResponse,
    RegulatoryStandardListResponse,
)
from app.schemas.retrieval import (
    ChunkData,
    Citation,
    RetrievalCandidate,
    RetrievalResult,
    VectorResult,
)
from app.schemas.system import (
    DashboardMetricsResponse,
    GlobalSearchResponse,
    NotificationResponse,
    SearchResultItem,
    TenantSettingsResponse,
    TenantSettingsUpdate,
    UserProfileResponse,
)

__all__ = [
    # Auth
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "TokenResponse",
    "TokenPayload",
    # Document
    "UploadResponse",
    "DocumentMetadata",
    "DocumentListResponse",
    # Models
    "ModelCreate",
    "ModelSummary",
    "ModelVersionDTO",
    "ModelExportData",
    # Privacy
    "MaskRequest",
    "MaskResponse",
    "RedactionLogResponse",
    # Compare
    "CompareRequest",
    "ComparisonDifference",
    "CompareResponse",
    # Gap Analysis
    "ComplianceGap",
    "GapAnalysisRequest",
    "GapAnalysisResponse",
    # Metrics / Analytics
    "MetricValue",
    "ModelValidationProfile",
    "PolicyResult",
    "BreachReport",
    "EWSSignal",
    "EWSReport",
    "AnalyticsResponse",
    # Query
    "QueryRequest",
    "QueryResponse",
    # Regulatory
    "RegulatoryQuery",
    "RegulatoryResponse",
    "RegulatoryStandardResponse",
    "RegulatoryStandardListResponse",
    # Retrieval
    "ChunkData",
    "VectorResult",
    "RetrievalCandidate",
    "Citation",
    "RetrievalResult",
    # System
    "DashboardMetricsResponse",
    "TenantSettingsUpdate",
    "TenantSettingsResponse",
    "NotificationResponse",
    "SearchResultItem",
    "GlobalSearchResponse",
    "UserProfileResponse",
]
