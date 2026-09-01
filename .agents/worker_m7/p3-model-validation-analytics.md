# Phase 3: Model Validation Analytics (Local Copy)

This skill provides step-by-step instructions to build the deterministic analytics engines for model validation documents.

## Step 1: ModelMetricsExtractor
Create `backend/app/services/analytics/model_metrics_extractor.py`

Implement a `ModelMetricsExtractor` class that extracts model validation metrics from raw document text using regular expressions. 
- Must handle multi-format parsing (e.g., `42%`, `0.42`, `42.0 percent`, `Gini of 45%`).
- **Discrimination metrics**: Gini Coefficient (pattern: `Gini\s*(?:coefficient|index)?\s*(?:of|:|=|is)?\s*(\d+\.?\d*)\s*%?`), AUC / AUROC, KS Statistic.
- **Stability metrics**: PSI (Population Stability Index).
- **Calibration metrics**: Hosmer-Lemeshow p-value, Brier Score.
- **Backtesting metrics**: PD accuracy ratio, observed vs predicted default rates.
- **Model parameters**: PD, LGD, EAD values and ranges.

The extractor should return a `ModelValidationProfile` Pydantic model. Each extracted metric should be stored as a `MetricValue(value: float, unit: str, raw_text: str, context: str)` where context is the surrounding sentence.

## Step 2: PolicyChecker
Create `backend/app/services/analytics/policy_checker.py`

Implement a `PolicyChecker` class to benchmark `ModelValidationProfile` against CBUAE MMG and architecture plan thresholds.
- **Gini**: >= 40.0% (WARNING: 40-44%)
- **AUC**: >= 0.70 (WARNING: 0.70-0.77)
- **KS**: >= 30.0% (WARNING: 30-33%)
- **PSI**: <= 0.25 (WARNING: 0.10-0.25)
- **IFRS 9 ECL Provision Coverage**: >= 50.0% (WARNING: 50-55%)
- **Capital Adequacy**: CAR >= 10.5%, Tier 1 >= 8.5%, NPA <= 5.0%

Implement the method `check(profile: ModelValidationProfile) -> BreachReport`.
A `BreachReport` contains a list of `PolicyResult(metric_name, value, threshold, status: PASS|WARNING|BREACH, rule_basis)`.

## Step 3: EarlyWarningDetector
Create `backend/app/services/analytics/ews_detector.py`

Implement an `EarlyWarningDetector` class for detecting model risk signals.
- **Qualitative signals** (regex patterns scanning document text):
  - Model not validated within regulatory timeline
  - Missing backtesting documentation
  - Override rates exceeding policy thresholds
  - Missing challenger model comparison
  - Inadequate documentation of model assumptions
  - Data quality issues or data gaps flagged
  - Model limitations not properly disclosed
  - Missing sensitivity analysis
  - Lack of independent validation
  - Missing model inventory registration

- **Quantitative triggers**:
  - Gini < 30% (severe discrimination failure)
  - PSI > 0.25 (significant population drift)
  - Observed/Expected default ratio outside 0.8-1.2 range
  - KS < 20% (weak separation)

Implement method `scan(raw_text: str, profile: ModelValidationProfile) -> EWSReport`.
An `EWSReport` contains: `grade: HIGH|MEDIUM|LOW|CLEAR`, `signals: list[EWSSignal]`, and `narrative: str`.
Each `EWSSignal` contains: `signal_name, description, severity, source_excerpt`.

## Step 4: Schemas
Create `backend/app/schemas/metrics.py`

Define the required Pydantic models:
- `MetricValue`
- `ModelValidationProfile`
- `PolicyResult`
- `BreachReport`
- `EWSSignal`
- `EWSReport`
- `AnalyticsResponse(profile, breach_report, ews_report)`
