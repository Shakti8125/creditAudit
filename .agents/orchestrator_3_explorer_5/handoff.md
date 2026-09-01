# Handoff Report — Analytics & Regulatory Verification Engine

## 1. Observation

Direct code observations across the analytics, policy, and schema modules:

1. **`backend/app/services/analytics/model_metrics_extractor.py`**:
   - Lines 16-19:
     ```python
     self.val_pattern = r"(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>%|percent|bps|bp)?"
     sep = r"\s*(?:of|is)?[:=|\|\s]+"
     ```
   - Lines 57-61:
     ```python
     clean_val_str = raw_val_str.replace(",", "")
     value = float(clean_val_str)
     ```
   - Line 23-37: `self.patterns` dict defines 15 regular expressions using `{sep}`. Parenthesized acronyms (e.g., `Population Stability Index (PSI): 0.04`, `Capital Adequacy Ratio (CAR): 14.5%`) and markdown bolding (e.g. `**AUC**: 0.82`, `| **AUC** | **0.82** |`) fail to match because `sep` does not include `(`, `)`, `*`, or `_`.

2. **`backend/app/services/analytics/policy_checker.py`**:
   - Line 29: `gini_warning_limit = gini_base_threshold * (1.0 + gini_tol)` is defined as dead code and replaced on line 31 by `gini_warn_threshold = gini_base_threshold + (gini_tol * 100)`.
   - Lines 63-280: Accurately checks CBUAE MMG thresholds:
     - AUC: `< 0.70` BREACH, `0.70 - 0.75` WARNING, `>= 0.75` PASS.
     - KS: `< 30.0%` BREACH, `30.0 - 33.0%` WARNING, `> 33.0%` PASS.
     - PSI: `> 0.25` BREACH, `0.10 - 0.25` WARNING, `< 0.10` PASS.
     - Hosmer-Lemeshow: `< 0.05` BREACH, `0.05 - 0.10` WARNING, `> 0.10` PASS.
     - Brier Score: `> 0.25` BREACH, `0.15 - 0.25` WARNING, `<= 0.15` PASS.
     - PD Accuracy Ratio: `< 40.0%` BREACH, `40.0 - 50.0%` WARNING, `>= 50.0%` PASS.
     - Observed vs Predicted Default Rate: `< 0.70` or `> 1.30` BREACH, `0.70-0.80` or `1.20-1.30` WARNING, `0.80-1.20` PASS.
     - CAR: `< 10.5%` BREACH, `>= 10.5%` PASS.
     - Tier 1: `< 8.5%` BREACH, `>= 8.5%` PASS.
     - NPA: `> 5.0%` BREACH, `<= 5.0%` PASS.

3. **`backend/app/services/analytics/ews_detector.py`**:
   - Lines 14-105: Scans 10 qualitative risk rules (delays, backtesting, overrides, challenger, assumptions, data quality, limitations, sensitivity, independence, inventory).
   - Lines 163-223: Evaluates quantitative signals for Gini, PSI, KS, and Observed vs Predicted default rates. Missing quantitative triggers for Hosmer-Lemeshow, Brier score, CAR, and NPA breaches.
   - Lines 238-247: EWS narrative only specifies dedicated strings for `HIGH` and `CLEAR` (0 signals); `MEDIUM` and `LOW` default to a generic count message.

4. **`backend/app/api/documents.py`**:
   - Lines 133-148:
     ```python
     metrics_extractor = ModelMetricsExtractor()
     profile = await run_in_threadpool(metrics_extractor.extract, raw_markdown)

     policy_checker = PolicyChecker()
     breach_report = await run_in_threadpool(policy_checker.check, profile)

     ews_detector = EarlyWarningDetector()
     ews_report = await run_in_threadpool(ews_detector.scan, raw_markdown, profile)
     ...
     model_version.metrics = profile.model_dump()
     model_version.gap_analysis = breach_report.model_dump()
     db.add(model_version)
     ```
     `TenantSettings` is not queried or passed into `policy_checker.check()`.
     `Model.status` is never updated based on `breach_report.results`, causing `GET /dashboard/metrics` to report 0 compliance issues.

5. **`backend/app/api/gap_analysis.py`**:
   - Lines 95-97:
     ```python
     result_str = await llm_router.generate(prompt, system_prompt=system_prompt, json_schema=schema)
     ```
     `EgressValidator` is not invoked prior to LLM call.

---

## 2. Logic Chain

1. **Regex Delimiter Limitation $\to$ Document Metric Extraction Misses**:
   - Observation: `sep = r"\s*(?:of|is)?[:=|\|\s]+"` does not match `(`, `)`, `*`, or `_`.
   - Evidence: Document strings like `Capital Adequacy Ratio (CAR): 14.5%` and markdown `| **AUC** | **0.82** |` contain characters outside `[:=|\|\s]`.
   - Deduction: Without supporting parenthesized acronyms and markdown formatting characters, standard Docling table cells and section headings fail extraction.

2. **Unset `Model.status` $\to$ Broken Dashboard Metrics**:
   - Observation: `api/documents.py` assigns `model_version.metrics` and `model_version.gap_analysis` but never assigns `model.status`.
   - Observation: `api/system.py` computes `compliance_issues` via `select(func.count()).where(Model.status.in_([ModelStatusEnum.BREACH, ModelStatusEnum.WARNING]))`.
   - Deduction: All models remain with `status = None`, meaning `compliance_issues` is always zero on the executive dashboard despite detected breaches.

3. **Omitted `TenantSettings` $\to$ Ignored Custom Thresholds**:
   - Observation: `policy_checker.check(profile)` accepts `settings: TenantSettings | None = None`. In `documents.py`, no settings object is passed.
   - Deduction: Custom thresholds (e.g. customized PSI tolerance or warning level) configured by tenants in `TenantSettings` have no effect during document processing.

4. **Missing `EgressValidator` in Gap Analysis $\to$ Privacy Rule Non-Compliance**:
   - Observation: `api/gap_analysis.py` directly executes `llm_router.generate(prompt, ...)` without `EgressValidator().validate(prompt, registry)`.
   - Deduction: Violates AGENTS.md Privacy Rules stating that the egress validator must run before any text is sent to an LLM provider.

---

## 3. Caveats

- **Network / Runtime Execution**: Per audit guidelines (R5 / Code-Only Explorer), live external LLM API calls and live Docling conversions were not executed.
- **Multi-column Table Heuristics**: The extractor's single-pass regex selects the first numeric column in multi-column tables. If a table contains both Development and Validation columns, additional column-aware parsing would be required to extract both separately.
- No other caveats.

---

## 4. Conclusion

The core analytics algorithms and CBUAE MMG regulatory rules are logically sound, fully compatible with Python 3.12, correctly parse units (% vs bps), and accurately implement Basel/CBUAE calibration metrics (Hosmer-Lemeshow, Brier, PD AR, and ODR/EDR ratios).

To achieve enterprise production readiness, six targeted remediations are identified:
1. Broaden `sep` regex in `model_metrics_extractor.py` to support markdown tags (`*`, `_`), parenthesized acronyms, and currency symbols.
2. Update parent `Model.status` (`PASS`, `WARNING`, `BREACH`) in `api/documents.py` upon document processing to ensure dashboard accuracy.
3. Query and pass `TenantSettings` to `PolicyChecker` during document upload.
4. Add `EgressValidator` validation to `api/gap_analysis.py`.
5. Remove dead code line 29 in `policy_checker.py`.
6. Add quantitative calibration and solvency checks to `EarlyWarningDetector`.

---

## 5. Verification Method

To independently verify these findings:
1. **Inspect Regex Separation**:
   Verify regex failure on `Capital Adequacy Ratio (CAR): 14.5%` and `| **AUC** | **0.82** |` using `model_metrics_extractor.py`.
2. **Inspect Model Status Persistence**:
   Review lines 144-148 of `backend/app/api/documents.py` to confirm `model.status` is never assigned.
3. **Inspect Dashboard Metrics Query**:
   Review lines 53-59 of `backend/app/api/system.py` to verify `compliance_issues` queries `Model.status`.
4. **Inspect Gap Analysis LLM Dispatch**:
   Review line 96 of `backend/app/api/gap_analysis.py` to confirm absence of `EgressValidator`.
5. **Run Existing Analytics Tests**:
   Execute pytest on `backend/tests/test_stress_analytics.py`.
