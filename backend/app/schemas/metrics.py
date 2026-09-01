from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class MetricValue(BaseModel):
    """Represents an extracted model validation metric."""
    model_config = ConfigDict(from_attributes=True)
    
    value: float
    unit: str
    raw_text: str
    context: str

class ModelValidationProfile(BaseModel):
    """A profile of extracted model validation metrics."""
    model_config = ConfigDict(from_attributes=True)
    
    # Discrimination metrics
    gini: Optional[MetricValue] = None
    auc: Optional[MetricValue] = None
    ks: Optional[MetricValue] = None
    
    # Stability metrics
    psi: Optional[MetricValue] = None
    
    # Calibration metrics
    hosmer_lemeshow_p_value: Optional[MetricValue] = None
    brier_score: Optional[MetricValue] = None
    
    # Backtesting metrics
    pd_accuracy_ratio: Optional[MetricValue] = None
    observed_vs_predicted_default_rate: Optional[MetricValue] = None
    
    # Model parameters
    pd_value: Optional[MetricValue] = None
    lgd_value: Optional[MetricValue] = None
    ead_value: Optional[MetricValue] = None
    
    # Other potential metrics
    ifrs9_ecl_provision_coverage: Optional[MetricValue] = None
    capital_adequacy_ratio: Optional[MetricValue] = None
    tier_1_ratio: Optional[MetricValue] = None
    npa_ratio: Optional[MetricValue] = None

class PolicyResult(BaseModel):
    """Result of benchmarking a metric against a threshold."""
    model_config = ConfigDict(from_attributes=True)
    
    metric_name: str
    value: float
    threshold: str
    status: str  # PASS, WARNING, BREACH
    rule_basis: str

class BreachReport(BaseModel):
    """Collection of policy results."""
    model_config = ConfigDict(from_attributes=True)
    
    results: list[PolicyResult] = Field(default_factory=list)

class EWSSignal(BaseModel):
    """Early warning signal based on qualitative or quantitative data."""
    model_config = ConfigDict(from_attributes=True)
    
    signal_name: str
    description: str
    severity: str  # HIGH, MEDIUM, LOW
    source_excerpt: str

class EWSReport(BaseModel):
    """Early warning system report."""
    model_config = ConfigDict(from_attributes=True)
    
    grade: str  # HIGH, MEDIUM, LOW, CLEAR
    signals: list[EWSSignal] = Field(default_factory=list)
    narrative: str

class AnalyticsResponse(BaseModel):
    """Aggregated analytics response."""
    model_config = ConfigDict(from_attributes=True)
    
    profile: ModelValidationProfile
    breach_report: BreachReport
    ews_report: EWSReport

class PopulationDecile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    decile: str
    expected: float
    actual: float

class PopulationDecilesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    deciles: list[PopulationDecile] = Field(default_factory=list)
