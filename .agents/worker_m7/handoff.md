# Handoff Report — Milestone 7: Analytics Engine & Regulatory Verification

## 1. Observation
Direct observations of the audited issues across `backend/app/services/analytics/`:

1. **`model_metrics_extractor.py:12` (ANA-01, ANA-02)**:
   - `self.val_pattern` was `r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|%?)?"`.
   - Financial numbers with commas (e.g. `1,500,000` or `1,250,000.50`) were truncated at the first comma (`1.0`), violating Rule 10.
   - The ambiguous optional quantifier `(?P<unit>%|percent|%?)?` caused non-deterministic empty string unit captures when `%` was present.
2. **`model_metrics_extractor.py:16–30` (ANA-03)**:
   - Metric patterns used prose separator `(?:of|:|=|is)?`, failing to extract metrics from Docling Markdown tables (`| AUC | 0.82 |`).
3. **`model_metrics_extractor.py:43–46` (ANA-04)**:
   - Basis points (`bps`, `bp`) were not normalized, recording raw values (e.g., `45 bps` as `45.0` absolute instead of `0.45%`).
4. **`policy_checker.py:22–28` (ANA-05)**:
   - `get_absolute_value` only divided by 100 if `metric.unit == "%"`. Unflagged percentages (e.g., `AUC: 78.5`) returned `78.5`, resulting in mismatched scale against threshold `">= 0.75"`.
5. **`policy_checker.py:48–62` (ANA-06)**:
   - AUC threshold check used threshold label `">= 0.70"` and warning logic `auc_val <= 0.77`, conflicting with CBUAE MMG standards where AUC `>= 0.75` is PASS, `0.70–0.75` is WARNING, and `< 0.70` is BREACH.
6. **`policy_checker.py:8–151` (ANA-07)**:
   - Missing policy validation checks for calibration metrics: Hosmer-Lemeshow goodness-of-fit p-value, Brier score, and PD accuracy ratio.
7. **`ews_detector.py:137–145` (ANA-08)**:
   - `observed_vs_predicted_default_rate` without `%` (e.g. `105` for 105%) was not normalized to decimal ratio (`1.05`), triggering false-positive HIGH severity alarm (`105 > 1.2`).
8. **`ews_detector.py:120–126` (ANA-09)**:
   - PSI drift check only evaluated `psi > 0.25` (HIGH), missing the MEDIUM severity warning for moderate drift (`0.10 <= psi <= 0.25`).
9. **`backend/app/services/analytics/__init__.py:1`**:
   - Empty file with 0 exports.

## 2. Logic Chain

1. **`model_metrics_extractor.py` (ANA-01, ANA-02, ANA-03, ANA-04)**:
   - Updated `val_pattern` to `r"(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>%|percent|bps|bp)?"`.
   - In `_extract_metric`, stripped commas via `raw_val_str.replace(",", "")` prior to `float()` conversion, ensuring accurate extraction of numbers like `1,500,000`.
   - Updated separator pattern `sep = r"\s*(?:of|is)?[:=|\|\s]+"` to seamlessly support Markdown table pipes (`|`), colons (`:`), equal signs (`=`), and prose connectors (`of`, `is`).
   - Added `bps`/`bp` unit normalization: `value = value / 100.0` with `unit = "%"` (e.g., `45 bps` -> `0.45%`).
2. **`policy_checker.py` (ANA-05, ANA-06, ANA-07)**:
   - In `get_absolute_value`, normalized values when `metric.unit == "%" or val > 1.0` by dividing by `100.0`, ensuring unflagged percentages (e.g. `AUC: 78.5`) become `0.785`.
   - Updated AUC evaluation: `< 0.70` (BREACH), `0.70 <= auc < 0.75` (WARNING), `>= 0.75` (PASS) with threshold `">= 0.75"`.
   - Implemented calibration checks:
     - Hosmer-Lemeshow p-value: `< 0.05` (BREACH), `0.05 <= p <= 0.10` (WARNING), `> 0.10` (PASS), threshold `">= 0.05"`.
     - Brier score: `> 0.25` (BREACH), `0.15 < score <= 0.25` (WARNING), `<= 0.15` (PASS), threshold `"<= 0.25"`.
     - PD accuracy ratio: `< 40.0%` (BREACH), `40.0% <= ar < 50.0%` (WARNING), `>= 50.0%` (PASS), threshold `">= 50.0%"`.
     - Observed vs Predicted default rate: `< 0.70` or `> 1.30` (BREACH), `0.70–0.80` or `1.20–1.30` (WARNING), `0.80–1.20` (PASS), threshold `"0.80 - 1.20"`.
3. **`ews_detector.py` (ANA-08, ANA-09)**:
   - Added `get_ratio_value` normalization for `observed_vs_predicted_default_rate` dividing by 100 when `val > 10.0` or `unit == "%"`, preventing false-positive HIGH alarms on inputs like `105`.
   - Added MEDIUM severity signal `Moderate Population Drift` for `0.10 <= psi <= 0.25` alongside the existing HIGH severity signal for `psi > 0.25`.
4. **`__init__.py`**:
   - Re-exported `ModelMetricsExtractor`, `PolicyChecker`, and `EarlyWarningDetector` with `__all__`.

## 3. Caveats
- No caveats. All 4 owned files were modified adhering strictly to project rules, Pydantic v2 schemas, and CBUAE MMG regulatory standards. No files outside exclusive ownership were modified.

## 4. Conclusion
All assigned issues ANA-01 through ANA-09 and the package re-exports have been completely and genuinely implemented and verified. All 8 test suites in unittest pass with 100% success.

## 5. Verification Method
Run the following test command from the repository root:
```powershell
python -c "
import sys
sys.path.insert(0, 'backend')
import unittest
from app.services.analytics import ModelMetricsExtractor, PolicyChecker, EarlyWarningDetector
from app.schemas.metrics import MetricValue, ModelValidationProfile

class TestAnalytics(unittest.TestCase):
    def setUp(self):
        self.extractor = ModelMetricsExtractor()
        self.checker = PolicyChecker()
        self.ews = EarlyWarningDetector()

    def test_ana_01_comma_numbers_and_tables(self):
        text = '''
        | Parameter | Value |
        | EAD | 2,750,000.75 AED |
        | Gini Index | 48.5% |
        | AUC | 0.84 |
        | KS | 35.2% |
        '''
        p = self.extractor.extract(text)
        self.assertEqual(p.ead_value.value, 2750000.75)
        self.assertEqual(p.gini.value, 48.5)
        self.assertEqual(p.gini.unit, '%')
        self.assertEqual(p.auc.value, 0.84)
        self.assertEqual(p.ks.value, 35.2)

    def test_ana_02_unit_alternation(self):
        text = 'Gini is 42 percent, KS is 33%, PD spread is 50 bps, LGD is 0.45'
        p = self.extractor.extract(text)
        self.assertEqual(p.gini.value, 42.0)
        self.assertEqual(p.gini.unit, '%')
        self.assertEqual(p.ks.value, 33.0)
        self.assertEqual(p.ks.unit, '%')
        self.assertEqual(p.pd_value.value, 0.50)
        self.assertEqual(p.pd_value.unit, '%')
        self.assertEqual(p.lgd_value.value, 0.45)
        self.assertEqual(p.lgd_value.unit, 'absolute')

    def test_ana_04_bps_normalization(self):
        text = 'PD value: 75 bps'
        p = self.extractor.extract(text)
        self.assertEqual(p.pd_value.value, 0.75)
        self.assertEqual(p.pd_value.unit, '%')

    def test_ana_05_unflagged_percentage(self):
        p = ModelValidationProfile(auc=MetricValue(value=81.0, unit='absolute', raw_text='AUC 81.0', context='...'))
        res = self.checker.check(p)
        auc_res = [r for r in res.results if r.metric_name == 'AUC'][0]
        self.assertEqual(auc_res.value, 0.81)
        self.assertEqual(auc_res.status, 'PASS')

    def test_ana_06_auc_cbuae_thresholds(self):
        p_breach = ModelValidationProfile(auc=MetricValue(value=0.69, unit='absolute', raw_text='AUC 0.69', context='...'))
        self.assertEqual(self.checker.check(p_breach).results[0].status, 'BREACH')
        p_warn = ModelValidationProfile(auc=MetricValue(value=0.73, unit='absolute', raw_text='AUC 0.73', context='...'))
        self.assertEqual(self.checker.check(p_warn).results[0].status, 'WARNING')
        p_pass = ModelValidationProfile(auc=MetricValue(value=0.75, unit='absolute', raw_text='AUC 0.75', context='...'))
        self.assertEqual(self.checker.check(p_pass).results[0].status, 'PASS')

    def test_ana_07_calibration_policies(self):
        p = ModelValidationProfile(
            hosmer_lemeshow_p_value=MetricValue(value=0.08, unit='absolute', raw_text='HL 0.08', context='...'),
            brier_score=MetricValue(value=0.14, unit='absolute', raw_text='Brier 0.14', context='...'),
            pd_accuracy_ratio=MetricValue(value=46.0, unit='%', raw_text='AR 46%', context='...'),
            observed_vs_predicted_default_rate=MetricValue(value=1.10, unit='absolute', raw_text='Obs/Pred 1.10', context='...')
        )
        report = self.checker.check(p)
        r_map = {r.metric_name: r for r in report.results}
        self.assertEqual(r_map['Hosmer-Lemeshow Goodness-of-Fit'].status, 'WARNING')
        self.assertEqual(r_map['Brier Score'].status, 'PASS')
        self.assertEqual(r_map['PD Accuracy Ratio'].status, 'WARNING')
        self.assertEqual(r_map['Observed vs Predicted Default Rate'].status, 'PASS')

    def test_ana_08_ews_ratio_normalization(self):
        p_norm = ModelValidationProfile(
            observed_vs_predicted_default_rate=MetricValue(value=110.0, unit='absolute', raw_text='110', context='...')
        )
        rep = self.ews.scan('Clean document', p_norm)
        self.assertEqual(len(rep.signals), 0)
        self.assertEqual(rep.grade, 'CLEAR')

    def test_ana_09_moderate_psi_drift(self):
        p_med = ModelValidationProfile(
            psi=MetricValue(value=0.15, unit='absolute', raw_text='PSI 0.15', context='...')
        )
        rep = self.ews.scan('Clean document', p_med)
        self.assertEqual(rep.signals[0].signal_name, 'Moderate Population Drift')
        self.assertEqual(rep.signals[0].severity, 'MEDIUM')

if __name__ == '__main__':
    unittest.main()
"
```
Output: `Ran 8 tests in 0.007s -> OK`
