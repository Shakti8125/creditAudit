from __future__ import annotations

import re
from typing import Any

from app.schemas.metrics import EWSReport, EWSSignal, MetricValue, ModelValidationProfile


class EarlyWarningDetector:
    """Detects model risk signals from qualitative text patterns and quantitative validation metrics."""

    def __init__(self) -> None:
        """Initialize qualitative signal detection patterns and severity mappings."""
        self.qualitative_patterns: list[dict[str, Any]] = [
            {
                "name": "Model Validation Delayed",
                "pattern": re.compile(
                    r"not (?:\w+\s+)?validated within regulatory timeline|validation delayed|overdue for validation",
                    re.IGNORECASE,
                ),
                "severity": "HIGH",
                "description": "Model has not been validated within the required regulatory timeline.",
            },
            {
                "name": "Missing Backtesting",
                "pattern": re.compile(
                    r"missing backtesting|no backtesting documentation|lack of backtesting",
                    re.IGNORECASE,
                ),
                "severity": "HIGH",
                "description": "Backtesting documentation is missing or inadequate.",
            },
            {
                "name": "High Override Rates",
                "pattern": re.compile(
                    r"override rates exceeding|high override rates|excessive overrides",
                    re.IGNORECASE,
                ),
                "severity": "MEDIUM",
                "description": "Manual override rates exceed policy thresholds.",
            },
            {
                "name": "Missing Challenger Model",
                "pattern": re.compile(
                    r"missing challenger model|no challenger model|lack of challenger",
                    re.IGNORECASE,
                ),
                "severity": "LOW",
                "description": "A challenger model comparison was not performed.",
            },
            {
                "name": "Inadequate Assumptions",
                "pattern": re.compile(
                    r"inadequate documentation of model assumptions|assumptions not documented|unclear assumptions",
                    re.IGNORECASE,
                ),
                "severity": "MEDIUM",
                "description": "Model assumptions are not properly documented.",
            },
            {
                "name": "Data Quality Issues",
                "pattern": re.compile(
                    r"data quality issues|data gaps|poor data quality|missing data elements",
                    re.IGNORECASE,
                ),
                "severity": "HIGH",
                "description": "Significant data quality issues or data gaps were flagged.",
            },
            {
                "name": "Undisclosed Limitations",
                "pattern": re.compile(
                    r"limitations not properly disclosed|undisclosed limitations|missing model limitations",
                    re.IGNORECASE,
                ),
                "severity": "MEDIUM",
                "description": "Model limitations are not fully or properly disclosed.",
            },
            {
                "name": "Missing Sensitivity Analysis",
                "pattern": re.compile(
                    r"missing sensitivity analysis|no sensitivity analysis|lack of sensitivity analysis",
                    re.IGNORECASE,
                ),
                "severity": "MEDIUM",
                "description": "Sensitivity analysis was not performed or documented.",
            },
            {
                "name": "Lack of Independent Validation",
                "pattern": re.compile(
                    r"lack of independent validation|validation not independent|conflict of interest in validation",
                    re.IGNORECASE,
                ),
                "severity": "HIGH",
                "description": "The validation process lacked required independence.",
            },
            {
                "name": "Missing Inventory Registration",
                "pattern": re.compile(
                    r"missing model inventory|not in model inventory|unregistered model",
                    re.IGNORECASE,
                ),
                "severity": "LOW",
                "description": "Model is not registered in the central model inventory.",
            },
        ]

    def scan(self, raw_text: str, profile: ModelValidationProfile) -> EWSReport:
        """Scan document text and quantitative profile for early warning risk signals.

        Args:
            raw_text: Raw or masked document text.
            profile: ModelValidationProfile with extracted quantitative metrics.

        Returns:
            EWSReport with overall grade, identified signals, and explanatory narrative.
        """
        signals: list[EWSSignal] = []

        # 1. Check qualitative signals from text
        for rule in self.qualitative_patterns:
            match = rule["pattern"].search(raw_text)
            if match:
                start_idx = max(0, match.start() - 60)
                end_idx = min(len(raw_text), match.end() + 60)
                excerpt = f"...{raw_text[start_idx:end_idx].strip()}..."

                signals.append(
                    EWSSignal(
                        signal_name=rule["name"],
                        description=rule["description"],
                        severity=rule["severity"],
                        source_excerpt=excerpt,
                    )
                )

        # 2. Helper functions for quantitative normalization
        def get_normalized_value(metric: MetricValue | None) -> float | None:
            if metric is None:
                return None
            val = metric.value
            if metric.unit == "absolute" and val <= 1.0:
                return val * 100.0
            return val

        def get_absolute_value(metric: MetricValue | None) -> float | None:
            if metric is None:
                return None
            val = metric.value
            if metric.unit == "%" or val > 1.0:
                return val / 100.0
            return val

        def get_ratio_value(metric: MetricValue | None) -> float | None:
            if metric is None:
                return None
            val = metric.value
            # Normalize percentage values or unflagged percentages (e.g., 105 or 105% -> 1.05) (ANA-08)
            if metric.unit == "%" or val > 10.0:
                return val / 100.0
            return val

        # 3. Quantitative triggers
        # 3.1 Discrimination triggers
        # Gini: < 30.0% is severe discrimination failure
        gini = get_normalized_value(profile.gini)
        if gini is not None and gini < 30.0:
            signals.append(
                EWSSignal(
                    signal_name="Severe Discrimination Failure",
                    description="Gini coefficient is below 30%.",
                    severity="HIGH",
                    source_excerpt=profile.gini.context if profile.gini else "N/A",
                )
            )

        # KS: < 20.0% is weak separation
        ks = get_normalized_value(profile.ks)
        if ks is not None and ks < 20.0:
            signals.append(
                EWSSignal(
                    signal_name="Weak Separation",
                    description="KS statistic is below 20%.",
                    severity="HIGH",
                    source_excerpt=profile.ks.context if profile.ks else "N/A",
                )
            )

        # 3.2 Stability triggers
        # PSI: > 0.25 (HIGH) and 0.10 <= PSI <= 0.25 (MEDIUM) (ANA-09)
        psi = get_absolute_value(profile.psi)
        if psi is not None:
            if psi > 0.25:
                signals.append(
                    EWSSignal(
                        signal_name="Significant Population Drift",
                        description="PSI is greater than 0.25.",
                        severity="HIGH",
                        source_excerpt=profile.psi.context if profile.psi else "N/A",
                    )
                )
            elif psi >= 0.10:
                signals.append(
                    EWSSignal(
                        signal_name="Moderate Population Drift",
                        description="PSI is between 0.10 and 0.25, indicating moderate population drift.",
                        severity="MEDIUM",
                        source_excerpt=profile.psi.context if profile.psi else "N/A",
                    )
                )

        # 3.3 Calibration triggers
        # Observed vs Predicted Default Rate: normalized to ratio (ANA-08)
        obs_vs_pred = get_ratio_value(profile.observed_vs_predicted_default_rate)
        if obs_vs_pred is not None:
            if obs_vs_pred < 0.8 or obs_vs_pred > 1.2:
                signals.append(
                    EWSSignal(
                        signal_name="Calibration Failure",
                        description="Observed/Expected default ratio is outside 0.8-1.2 range.",
                        severity="HIGH",
                        source_excerpt=profile.observed_vs_predicted_default_rate.context
                        if profile.observed_vs_predicted_default_rate
                        else "N/A",
                    )
                )

        # Hosmer-Lemeshow Goodness-of-Fit: < 0.05 indicates severe miscalibration
        hl = get_absolute_value(profile.hosmer_lemeshow_p_value)
        if hl is not None:
            if hl < 0.05:
                signals.append(
                    EWSSignal(
                        signal_name="Severe Calibration Defect",
                        description="Hosmer-Lemeshow p-value is below 0.05, indicating significant default rate miscalibration.",
                        severity="HIGH",
                        source_excerpt=profile.hosmer_lemeshow_p_value.context
                        if profile.hosmer_lemeshow_p_value
                        else "N/A",
                    )
                )
            elif hl <= 0.10:
                signals.append(
                    EWSSignal(
                        signal_name="Marginal Calibration Fit",
                        description="Hosmer-Lemeshow p-value is between 0.05 and 0.10, indicating borderline calibration goodness-of-fit.",
                        severity="MEDIUM",
                        source_excerpt=profile.hosmer_lemeshow_p_value.context
                        if profile.hosmer_lemeshow_p_value
                        else "N/A",
                    )
                )

        # Brier Score: > 0.25 indicates poor forecast accuracy
        brier = get_absolute_value(profile.brier_score)
        if brier is not None:
            if brier > 0.25:
                signals.append(
                    EWSSignal(
                        signal_name="High Prediction Error",
                        description="Brier Score exceeds 0.25, indicating severe probability forecast inaccuracy.",
                        severity="HIGH",
                        source_excerpt=profile.brier_score.context if profile.brier_score else "N/A",
                    )
                )
            elif brier > 0.15:
                signals.append(
                    EWSSignal(
                        signal_name="Elevated Brier Score",
                        description="Brier Score is between 0.15 and 0.25, indicating elevated probability forecast error.",
                        severity="MEDIUM",
                        source_excerpt=profile.brier_score.context if profile.brier_score else "N/A",
                    )
                )

        # PD Accuracy Ratio: < 40% indicates inadequate discrimination
        pd_ar = get_normalized_value(profile.pd_accuracy_ratio)
        if pd_ar is not None:
            if pd_ar < 40.0:
                signals.append(
                    EWSSignal(
                        signal_name="Inadequate Rating Discrimination",
                        description="PD Accuracy Ratio is below 40%, indicating poor discriminatory power in rating assignments.",
                        severity="HIGH",
                        source_excerpt=profile.pd_accuracy_ratio.context if profile.pd_accuracy_ratio else "N/A",
                    )
                )
            elif pd_ar < 50.0:
                signals.append(
                    EWSSignal(
                        signal_name="Suboptimal Rating Accuracy",
                        description="PD Accuracy Ratio is between 40% and 50%, below the recommended 50% benchmark.",
                        severity="MEDIUM",
                        source_excerpt=profile.pd_accuracy_ratio.context if profile.pd_accuracy_ratio else "N/A",
                    )
                )

        # 3.4 Prudential Solvency triggers (CBUAE MMG & Basel III)
        # Capital Adequacy Ratio (CAR): < 10.5% breach
        car = get_normalized_value(profile.capital_adequacy_ratio)
        if car is not None:
            if car < 10.5:
                signals.append(
                    EWSSignal(
                        signal_name="Capital Adequacy Breach",
                        description="Capital Adequacy Ratio (CAR) is below the CBUAE MMG regulatory minimum of 10.5%.",
                        severity="HIGH",
                        source_excerpt=profile.capital_adequacy_ratio.context
                        if profile.capital_adequacy_ratio
                        else "N/A",
                    )
                )
            elif car < 12.0:
                signals.append(
                    EWSSignal(
                        signal_name="Capital Adequacy Buffer Warning",
                        description="Capital Adequacy Ratio (CAR) is below 12.0%, approaching the regulatory minimum.",
                        severity="MEDIUM",
                        source_excerpt=profile.capital_adequacy_ratio.context
                        if profile.capital_adequacy_ratio
                        else "N/A",
                    )
                )

        # Tier 1 Capital Ratio: < 8.5% breach
        tier1 = get_normalized_value(profile.tier_1_ratio)
        if tier1 is not None:
            if tier1 < 8.5:
                signals.append(
                    EWSSignal(
                        signal_name="Tier 1 Capital Deficiency",
                        description="Tier 1 Capital Ratio is below the CBUAE regulatory requirement of 8.5%.",
                        severity="HIGH",
                        source_excerpt=profile.tier_1_ratio.context if profile.tier_1_ratio else "N/A",
                    )
                )
            elif tier1 < 9.5:
                signals.append(
                    EWSSignal(
                        signal_name="Tier 1 Capital Buffer Warning",
                        description="Tier 1 Capital Ratio is below 9.5%, nearing the regulatory minimum boundary.",
                        severity="MEDIUM",
                        source_excerpt=profile.tier_1_ratio.context if profile.tier_1_ratio else "N/A",
                    )
                )

        # NPA Ratio: > 5.0% prudential breach
        npa = get_normalized_value(profile.npa_ratio)
        if npa is not None:
            if npa > 5.0:
                signals.append(
                    EWSSignal(
                        signal_name="Excessive Non-Performing Assets",
                        description="NPA ratio exceeds the prudential tolerance limit of 5.0%.",
                        severity="HIGH",
                        source_excerpt=profile.npa_ratio.context if profile.npa_ratio else "N/A",
                    )
                )
            elif npa >= 4.0:
                signals.append(
                    EWSSignal(
                        signal_name="Elevated NPA Ratio",
                        description="NPA ratio is between 4.0% and 5.0%, nearing the prudential maximum.",
                        severity="MEDIUM",
                        source_excerpt=profile.npa_ratio.context if profile.npa_ratio else "N/A",
                    )
                )

        # IFRS 9 ECL Provision Coverage: < 50% breach
        ecl = get_normalized_value(profile.ifrs9_ecl_provision_coverage)
        if ecl is not None:
            if ecl < 50.0:
                signals.append(
                    EWSSignal(
                        signal_name="ECL Under-Provisioning",
                        description="IFRS 9 ECL Provision Coverage is below the required 50.0% threshold.",
                        severity="HIGH",
                        source_excerpt=profile.ifrs9_ecl_provision_coverage.context
                        if profile.ifrs9_ecl_provision_coverage
                        else "N/A",
                    )
                )
            elif ecl <= 55.0:
                signals.append(
                    EWSSignal(
                        signal_name="Marginal ECL Provision Coverage",
                        description="IFRS 9 ECL Provision Coverage is between 50.0% and 55.0%, indicating thin provisioning cushion.",
                        severity="MEDIUM",
                        source_excerpt=profile.ifrs9_ecl_provision_coverage.context
                        if profile.ifrs9_ecl_provision_coverage
                        else "N/A",
                    )
                )

        # 4. Determine overall grade
        has_high = any(s.severity == "HIGH" for s in signals)
        has_med = any(s.severity == "MEDIUM" for s in signals)
        has_low = any(s.severity == "LOW" for s in signals)

        if has_high:
            grade = "HIGH"
        elif has_med:
            grade = "MEDIUM"
        elif has_low:
            grade = "LOW"
        else:
            grade = "CLEAR"

        narrative = f"Detected {len(signals)} early warning signals."
        if len(signals) == 0:
            narrative = "No early warning signals detected. The model appears stable based on available data."
        elif grade == "HIGH":
            narrative = "Critical risks identified. Immediate attention and potential model remediation required."

        return EWSReport(
            grade=grade,
            signals=signals,
            narrative=narrative,
        )
