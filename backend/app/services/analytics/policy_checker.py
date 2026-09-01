from __future__ import annotations

from app.schemas.metrics import BreachReport, MetricValue, ModelValidationProfile, PolicyResult
from app.models.system import TenantSettings


class PolicyChecker:
    """Benchmarks ModelValidationProfile against CBUAE MMG and internal architecture thresholds."""

    def check(self, profile: ModelValidationProfile, settings: TenantSettings | None = None) -> BreachReport:
        """Benchmark all available metrics in the validation profile against regulatory standards.

        Args:
            profile: ModelValidationProfile containing extracted metrics.
            settings: Optional TenantSettings for parameterized thresholds.

        Returns:
            BreachReport containing list of PolicyResult evaluations.
        """
        results: list[PolicyResult] = []

        # Default settings if none provided
        psi_warn = settings.psi_warning_threshold if settings else 0.10
        psi_breach = settings.psi_breach_threshold if settings else 0.25
        gini_tol = settings.gini_tolerance if settings else 0.05
        
        # Calculate thresholds
        # Gini: Base threshold is 40.0% with additive tenant tolerance (e.g. 40.0 + 5.0 = 45.0%)
        gini_base_threshold = 40.0
        gini_warn_threshold = gini_base_threshold + (gini_tol * 100)

        # Helper to normalize percentage metrics to 0-100 scale
        def get_normalized_value(metric: MetricValue | None) -> float | None:
            if metric is None:
                return None
            val = metric.value
            # If the unit is absolute and val <= 1.0, it's represented as a decimal fraction (e.g. 0.42 -> 42.0%)
            if metric.unit == "absolute" and val <= 1.0:
                return val * 100.0
            return val

        # Helper to normalize decimal/scale metrics to 0-1 scale (ANA-05)
        def get_absolute_value(metric: MetricValue | None) -> float | None:
            if metric is None:
                return None
            val = metric.value
            # If unit is % or val > 1.0 (unflagged percentage like AUC: 78.5), normalize to decimal scale
            if metric.unit == "%" or val > 1.0:
                return val / 100.0
            return val

        # Helper for ratio metrics (e.g., observed vs predicted default rate where acceptable is ~1.0)
        def get_ratio_value(metric: MetricValue | None) -> float | None:
            if metric is None:
                return None
            val = metric.value
            # If unit is % or val > 10.0 (e.g. 105 or 105%), normalize to ratio scale
            if metric.unit == "%" or val > 10.0:
                return val / 100.0
            return val

        # 1. Discrimination Metrics
        # Gini
        gini_val = get_normalized_value(profile.gini)
        if gini_val is not None:
            if gini_val < gini_base_threshold:
                status = "BREACH"
            elif gini_val <= gini_warn_threshold:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="Gini Coefficient",
                    value=gini_val,
                    threshold=f">= {gini_base_threshold}%",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # AUC: >= 0.75 (PASS: >= 0.75, WARNING: 0.70-0.75, BREACH: < 0.70) (ANA-06)
        auc_val = get_absolute_value(profile.auc)
        if auc_val is not None:
            if auc_val < 0.70:
                status = "BREACH"
            elif auc_val < 0.75:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="AUC",
                    value=auc_val,
                    threshold=">= 0.75",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # KS: >= 30.0% (PASS: > 33.0%, WARNING: 30.0-33.0%, BREACH: < 30.0%)
        ks_val = get_normalized_value(profile.ks)
        if ks_val is not None:
            if ks_val < 30.0:
                status = "BREACH"
            elif ks_val <= 33.0:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="KS Statistic",
                    value=ks_val,
                    threshold=">= 30.0%",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # 2. Stability Metrics
        # PSI
        psi_val = get_absolute_value(profile.psi)
        if psi_val is not None:
            if psi_val > psi_breach:
                status = "BREACH"
            elif psi_val >= psi_warn:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="PSI",
                    value=psi_val,
                    threshold=f"<= {psi_breach}",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # 3. Calibration Metrics (ANA-07)
        # Hosmer-Lemeshow p-value: >= 0.05 (PASS: > 0.10, WARNING: 0.05-0.10, BREACH: < 0.05)
        hl_val = get_absolute_value(profile.hosmer_lemeshow_p_value)
        if hl_val is not None:
            if hl_val < 0.05:
                status = "BREACH"
            elif hl_val <= 0.10:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="Hosmer-Lemeshow Goodness-of-Fit",
                    value=hl_val,
                    threshold=">= 0.05",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # Brier Score: <= 0.25 (PASS: <= 0.15, WARNING: 0.15-0.25, BREACH: > 0.25) (ANA-07)
        brier_val = get_absolute_value(profile.brier_score)
        if brier_val is not None:
            if brier_val > 0.25:
                status = "BREACH"
            elif brier_val > 0.15:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="Brier Score",
                    value=brier_val,
                    threshold="<= 0.25",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # 4. Backtesting Metrics (ANA-07)
        # PD Accuracy Ratio: >= 50.0% (PASS: >= 50.0%, WARNING: 40.0-50.0%, BREACH: < 40.0%)
        pd_ar_val = get_normalized_value(profile.pd_accuracy_ratio)
        if pd_ar_val is not None:
            if pd_ar_val < 40.0:
                status = "BREACH"
            elif pd_ar_val < 50.0:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="PD Accuracy Ratio",
                    value=pd_ar_val,
                    threshold=">= 50.0%",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # Observed vs Predicted Default Rate: 0.80 - 1.20 (PASS: 0.80-1.20, WARNING: 0.70-0.80 or 1.20-1.30, BREACH: < 0.70 or > 1.30)
        obs_pred_val = get_ratio_value(profile.observed_vs_predicted_default_rate)
        if obs_pred_val is not None:
            if obs_pred_val < 0.70 or obs_pred_val > 1.30:
                status = "BREACH"
            elif obs_pred_val < 0.80 or obs_pred_val > 1.20:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="Observed vs Predicted Default Rate",
                    value=obs_pred_val,
                    threshold="0.80 - 1.20",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # 5. Financial & Regulatory Policy Checks
        # IFRS 9 ECL Provision Coverage: >= 50.0% (WARNING: 50-55%)
        ecl_val = get_normalized_value(profile.ifrs9_ecl_provision_coverage)
        if ecl_val is not None:
            if ecl_val < 50.0:
                status = "BREACH"
            elif ecl_val <= 55.0:
                status = "WARNING"
            else:
                status = "PASS"
            results.append(
                PolicyResult(
                    metric_name="IFRS 9 ECL Provision Coverage",
                    value=ecl_val,
                    threshold=">= 50.0%",
                    status=status,
                    rule_basis="Internal Architecture Plan",
                )
            )

        # Capital Adequacy: CAR >= 10.5%
        car_val = get_normalized_value(profile.capital_adequacy_ratio)
        if car_val is not None:
            status = "PASS" if car_val >= 10.5 else "BREACH"
            results.append(
                PolicyResult(
                    metric_name="Capital Adequacy Ratio (CAR)",
                    value=car_val,
                    threshold=">= 10.5%",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # Tier 1 >= 8.5%
        tier1_val = get_normalized_value(profile.tier_1_ratio)
        if tier1_val is not None:
            status = "PASS" if tier1_val >= 8.5 else "BREACH"
            results.append(
                PolicyResult(
                    metric_name="Tier 1 Ratio",
                    value=tier1_val,
                    threshold=">= 8.5%",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        # NPA <= 5.0%
        npa_val = get_normalized_value(profile.npa_ratio)
        if npa_val is not None:
            status = "PASS" if npa_val <= 5.0 else "BREACH"
            results.append(
                PolicyResult(
                    metric_name="NPA Ratio",
                    value=npa_val,
                    threshold="<= 5.0%",
                    status=status,
                    rule_basis="CBUAE MMG",
                )
            )

        return BreachReport(results=results)
