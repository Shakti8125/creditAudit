from __future__ import annotations

import pytest
from app.services.analytics.model_metrics_extractor import ModelMetricsExtractor
from app.services.analytics.policy_checker import PolicyChecker
from app.services.analytics.ews_detector import EarlyWarningDetector


def test_metrics_extraction_from_tables_and_comma_numbers():
    """Verify extraction handles Markdown table pipes and formatted comma numbers."""
    extractor = ModelMetricsExtractor()

    text = (
        "# Model Validation Profile\n\n"
        "| Metric | Value |\n"
        "|---|---|\n"
        "| AUC | 0.82 |\n"
        "| Gini coefficient | 64.0% |\n"
        "| KS statistic | 38.5% |\n"
        "| PSI | 0.04 |\n"
        "| Hosmer-Lemeshow p-value | 0.18 |\n"
        "| Brier Score | 0.11 |\n"
        "| Capital Adequacy Ratio | 14.5% |\n"
        "| Tier 1 ratio | 12.0% |\n"
        "| NPA ratio | 3.2% |\n\n"
        "The model portfolio has total EAD of 1,500,000 with PD spread of 45 bps."
    )

    profile = extractor.extract(text)

    assert profile.auc is not None
    assert profile.auc.value == 0.82

    assert profile.gini is not None
    assert profile.gini.value == 64.0
    assert profile.gini.unit == "%"

    assert profile.ks is not None
    assert profile.ks.value == 38.5

    assert profile.psi is not None
    assert profile.psi.value == 0.04

    assert profile.hosmer_lemeshow_p_value is not None
    assert profile.hosmer_lemeshow_p_value.value == 0.18

    assert profile.brier_score is not None
    assert profile.brier_score.value == 0.11

    assert profile.capital_adequacy_ratio is not None
    assert profile.capital_adequacy_ratio.value == 14.5

    assert profile.tier_1_ratio is not None
    assert profile.tier_1_ratio.value == 12.0

    assert profile.npa_ratio is not None
    assert profile.npa_ratio.value == 3.2

    # Verify bps normalization: 45 bps -> 0.45%
    assert profile.pd_value is not None
    assert profile.pd_value.value == 0.45
    assert profile.pd_value.unit == "%"


def test_policy_checker_regulatory_benchmarks():
    """Verify policy checker correctly categorizes PASS, WARNING, and BREACH against CBUAE MMG standards."""
    extractor = ModelMetricsExtractor()
    checker = PolicyChecker()

    # 1. Compliant model
    pass_text = (
        "AUC: 0.82\n"
        "Gini: 65%\n"
        "KS: 39%\n"
        "PSI: 0.04\n"
        "Hosmer-Lemeshow: 0.15\n"
        "Brier: 0.10\n"
        "CAR: 15.0%\n"
        "Tier 1: 12.5%\n"
        "NPA: 2.5%"
    )
    pass_profile = extractor.extract(pass_text)
    pass_report = checker.check(pass_profile)
    statuses = {r.metric_name: r.status for r in pass_report.results}
    assert all(s == "PASS" for s in statuses.values()), f"Expected all PASS, got: {statuses}"

    # 2. Breaching model
    breach_text = (
        "AUC: 0.58\n"
        "Gini: 28%\n"
        "KS: 22%\n"
        "PSI: 0.35\n"
        "Hosmer-Lemeshow: 0.02\n"
        "Brier: 0.30\n"
        "CAR: 8.0%\n"
        "Tier 1: 6.0%\n"
        "NPA: 8.5%"
    )
    breach_profile = extractor.extract(breach_text)
    breach_report = checker.check(breach_profile)
    breach_statuses = {r.metric_name: r.status for r in breach_report.results}
    assert all(s == "BREACH" for s in breach_statuses.values()), f"Expected all BREACH, got: {breach_statuses}"

    # 3. Warning model
    warn_text = "AUC: 0.72\nGini: 42%\nKS: 31%\nPSI: 0.15\nHosmer-Lemeshow: 0.08\nBrier: 0.20"
    warn_profile = extractor.extract(warn_text)
    warn_report = checker.check(warn_profile)
    warn_statuses = {r.metric_name: r.status for r in warn_report.results}
    assert all(s == "WARNING" for s in warn_statuses.values()), f"Expected all WARNING, got: {warn_statuses}"


def test_early_warning_detector_scans():
    """Verify EWSDetector flags both qualitative risk phrases and quantitative breaches."""
    extractor = ModelMetricsExtractor()
    detector = EarlyWarningDetector()

    text = (
        "The model development documentation has significant data quality issues and data gaps. "
        "Furthermore, the model is overdue for validation and validation delayed past timeline. "
        "There is a lack of independent validation. "
        "AUC: 0.55\nPSI: 0.30"
    )
    profile = extractor.extract(text)
    report = detector.scan(text, profile)

    signal_names = [s.signal_name for s in report.signals]
    assert "Data Quality Issues" in signal_names
    assert "Model Validation Delayed" in signal_names
    assert "Lack of Independent Validation" in signal_names
    assert "Significant Population Drift" in signal_names
    assert report.grade == "HIGH"


def test_parenthesized_acronyms_and_bold_markdown_extraction():
    """Verify extraction handles parenthesized acronyms, markdown bolding, and Docling table formatting."""
    extractor = ModelMetricsExtractor()

    text = (
        "# Model Summary\n\n"
        "| Metric Name | Value |\n"
        "|---|---|\n"
        "| **AUC** | **0.82** |\n"
        "| Population Stability Index (PSI) | 0.04 |\n"
        "| Probability of Default (PD) | 1.25% |\n"
        "| Loss Given Default (LGD) | 42.0% |\n"
        "| Exposure at Default (EAD) | 2,450,000.75 |\n"
        "| Capital Adequacy Ratio (CAR) | 16.2% |\n"
        "| Hosmer-Lemeshow (H-L) | 0.12 |\n"
        "| PD Accuracy Ratio (AR) | 48.0% |\n"
        "| Non-Performing Assets (NPA) | 2.1% |\n"
        "| IFRS 9 ECL Provision Coverage | 58.5% |\n"
    )

    profile = extractor.extract(text)

    assert profile.auc is not None
    assert profile.auc.value == 0.82

    assert profile.psi is not None
    assert profile.psi.value == 0.04

    assert profile.pd_value is not None
    assert profile.pd_value.value == 1.25
    assert profile.pd_value.unit == "%"

    assert profile.lgd_value is not None
    assert profile.lgd_value.value == 42.0
    assert profile.lgd_value.unit == "%"

    assert profile.ead_value is not None
    assert profile.ead_value.value == 2450000.75

    assert profile.capital_adequacy_ratio is not None
    assert profile.capital_adequacy_ratio.value == 16.2

    assert profile.hosmer_lemeshow_p_value is not None
    assert profile.hosmer_lemeshow_p_value.value == 0.12

    assert profile.pd_accuracy_ratio is not None
    assert profile.pd_accuracy_ratio.value == 48.0

    assert profile.npa_ratio is not None
    assert profile.npa_ratio.value == 2.1

    assert profile.ifrs9_ecl_provision_coverage is not None
    assert profile.ifrs9_ecl_provision_coverage.value == 58.5


def test_enhanced_quantitative_early_warning_triggers():
    """Verify enhanced quantitative trigger detection for calibration and prudential solvency."""
    from app.services.analytics.early_warning import EarlyWarningDetector as EWSAliasDetector

    extractor = ModelMetricsExtractor()
    detector = EWSAliasDetector()

    # Model with calibration and prudential solvency defects
    defect_text = (
        "Hosmer-Lemeshow: 0.01\n"
        "Brier Score: 0.32\n"
        "PD Accuracy Ratio: 32.0%\n"
        "CAR: 9.5%\n"
        "Tier 1: 7.0%\n"
        "NPA: 6.8%\n"
        "IFRS 9 ECL Provision Coverage: 42.0%"
    )

    profile = extractor.extract(defect_text)
    report = detector.scan(defect_text, profile)

    signal_names = [s.signal_name for s in report.signals]
    assert "Severe Calibration Defect" in signal_names
    assert "High Prediction Error" in signal_names
    assert "Inadequate Rating Discrimination" in signal_names
    assert "Capital Adequacy Breach" in signal_names
    assert "Tier 1 Capital Deficiency" in signal_names
    assert "Excessive Non-Performing Assets" in signal_names
    assert "ECL Under-Provisioning" in signal_names
    assert report.grade == "HIGH"

