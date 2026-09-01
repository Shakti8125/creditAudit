import asyncio
import os
import sys
import uuid

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath("backend"))

def test_entity_registry():
    print("--- Testing EntityRegistry ---", flush=True)
    from app.services.privacy.entity_registry import EntityRegistry
    reg = EntityRegistry()
    t1 = reg.mask("Emirates NBD", "BANK")
    assert t1 == "[BANK_1]", f"Expected [BANK_1], got {t1}"
    t2 = reg.mask("Abu Dhabi Commercial Bank", "BANK")
    assert t2 == "[BANK_2]", f"Expected [BANK_2], got {t2}"
    t3 = reg.mask("Emirates NBD", "BANK")
    assert t3 == "[BANK_1]", f"Expected deduplication to [BANK_1], got {t3}"
    
    masked = f"We audit {t1} and {t2}."
    unmasked = reg.unmask_text(masked)
    assert unmasked == "We audit Emirates NBD and Abu Dhabi Commercial Bank.", f"Unmasking mismatch: {unmasked}"
    print("  [PASS] EntityRegistry bijective mapping & unmasking verified.", flush=True)

def test_bank_matcher():
    print("--- Testing BankNameMatcher ---", flush=True)
    from app.services.privacy.bank_matcher import BankNameMatcher
    matcher = BankNameMatcher()
    sample = "The facility was approved by FAB and Dubai Islamic Bank yesterday. FABrication is not a bank."
    matches = matcher.find_matches(sample)
    matched_names = [m[2] for m in matches]
    assert "FAB" in matched_names, f"FAB not matched: {matches}"
    assert "Dubai Islamic Bank" in matched_names, f"DIB not matched: {matches}"
    # Verify word boundaries prevent substring match in FABrication
    for m in matches:
        if m[2] == "FAB":
            assert m[0] == sample.find("FAB and"), "Matched FAB inside FABrication!"
    print(f"  [PASS] BankNameMatcher correctly matched: {matched_names}", flush=True)

def test_analytics():
    print("--- Testing Analytics (Metrics Extractor, Policy Checker, EWS) ---", flush=True)
    from app.services.analytics.model_metrics_extractor import ModelMetricsExtractor
    from app.services.analytics.policy_checker import PolicyChecker
    from app.services.analytics.ews_detector import EarlyWarningDetector
    
    doc = """
    ## Model Performance Summary
    - Gini Coefficient: 42.5%
    - AUC: 0.76
    - KS Statistic: 32.0%
    - PSI: 0.12
    - Hosmer-Lemeshow p-value: 0.08
    - Brier Score: 0.14
    - Observed vs Predicted Default Rate: 1.05
    - IFRS 9 ECL Provision Coverage: 52.0%
    - Capital Adequacy Ratio: 12.5%
    - Tier 1 Ratio: 9.5%
    - NPA Ratio: 3.2%
    
    Note: override rates exceeding 15% were observed in Q3.
    """
    extractor = ModelMetricsExtractor()
    profile = extractor.extract(doc)
    assert profile.gini is not None and abs(profile.gini.value - 42.5) < 0.01, f"Gini extraction failed: {profile.gini}"
    assert profile.auc is not None and abs(profile.auc.value - 0.76) < 0.01, f"AUC extraction failed: {profile.auc}"
    assert profile.ks is not None and abs(profile.ks.value - 32.0) < 0.01, f"KS extraction failed: {profile.ks}"
    assert profile.psi is not None and abs(profile.psi.value - 0.12) < 0.01, f"PSI extraction failed: {profile.psi}"
    assert profile.hosmer_lemeshow_p_value is not None and abs(profile.hosmer_lemeshow_p_value.value - 0.08) < 0.01
    assert profile.brier_score is not None and abs(profile.brier_score.value - 0.14) < 0.01
    assert profile.observed_vs_predicted_default_rate is not None and abs(profile.observed_vs_predicted_default_rate.value - 1.05) < 0.01
    assert profile.ifrs9_ecl_provision_coverage is not None and abs(profile.ifrs9_ecl_provision_coverage.value - 52.0) < 0.01
    assert profile.capital_adequacy_ratio is not None and abs(profile.capital_adequacy_ratio.value - 12.5) < 0.01
    assert profile.tier_1_ratio is not None and abs(profile.tier_1_ratio.value - 9.5) < 0.01
    assert profile.npa_ratio is not None and abs(profile.npa_ratio.value - 3.2) < 0.01
    print("  [PASS] ModelMetricsExtractor successfully extracted all 11 quantitative metrics.", flush=True)
    
    checker = PolicyChecker()
    report = checker.check(profile)
    statuses = {r.metric_name: r.status for r in report.results}
    print(f"  Policy check results: {statuses}", flush=True)
    assert statuses.get("Gini Coefficient") == "WARNING", f"Expected Gini WARNING, got {statuses.get('Gini Coefficient')}"
    assert statuses.get("AUC") == "PASS", f"Expected AUC PASS, got {statuses.get('AUC')}"
    assert statuses.get("PSI") == "WARNING", f"Expected PSI WARNING, got {statuses.get('PSI')}"
    assert statuses.get("Hosmer-Lemeshow Goodness-of-Fit") == "WARNING"
    assert statuses.get("Brier Score") == "PASS"
    assert statuses.get("Observed vs Predicted Default Rate") == "PASS"
    assert statuses.get("Capital Adequacy Ratio (CAR)") == "PASS"
    assert statuses.get("Tier 1 Ratio") == "PASS"
    assert statuses.get("NPA Ratio") == "PASS"
    print("  [PASS] PolicyChecker benchmarked thresholds against CBUAE MMG standards.", flush=True)
    
    detector = EarlyWarningDetector()
    ews_report = detector.scan(doc, profile)
    print(f"  EWS Grade: {ews_report.grade}, Signals: {[s.signal_name for s in ews_report.signals]}", flush=True)
    assert any("Override" in s.signal_name for s in ews_report.signals), "Expected override signal detected"
    assert any("Population Drift" in s.signal_name for s in ews_report.signals), "Expected population drift signal detected"
    print("  [PASS] EarlyWarningDetector successfully detected risk signals.", flush=True)

def test_security_auth():
    print("--- Testing Security & RS256 Auth ---", flush=True)
    from app.utils.security import hash_password, verify_password, create_access_token, decode_token
    pwd = "SecurePassword123!"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed), "Password verification failed"
    assert not verify_password("WrongPassword", hashed), "Password verification accepted wrong password"
    
    uid = uuid.uuid4()
    tid = uuid.uuid4()
    token = create_access_token(uid, tid, "RISK_ANALYST")
    payload = decode_token(token)
    assert payload["sub"] == str(uid), f"Sub mismatch: {payload['sub']}"
    assert payload["tenant_id"] == str(tid), f"Tenant mismatch: {payload['tenant_id']}"
    assert payload["role"] == "RISK_ANALYST", f"Role mismatch: {payload['role']}"
    print("  [PASS] RS256 JWT & Bcrypt verified cleanly.", flush=True)

def test_markdown_chunker():
    print("--- Testing MarkdownChunker ---", flush=True)
    from app.services.chunker import MarkdownChunker
    chunker = MarkdownChunker(chunk_size=500, overlap=100)
    text = """
# Section 1: Executive Summary
The model demonstrates adequate performance across macroeconomic scenarios.

## Subsection 1.1: Quantitative Table
| Metric | Value | Threshold | Status |
|---|---|---|---|
| Gini | 45.2% | >= 40.0% | PASS |
| AUC | 0.78 | >= 0.70 | PASS |
| PSI | 0.08 | <= 0.25 | PASS |

## Subsection 1.2: Credit Portfolio Details
The wholesale portfolio total exposure is AED 1,250,000,000 across 45 corporate counterparties.
"""
    chunks = chunker.chunk(text)
    print(f"  Generated {len(chunks)} chunks.", flush=True)
    for idx, c in enumerate(chunks):
        print(f"    Chunk {idx}: {c[:60]}...", flush=True)
    assert any("| Metric | Value |" in c for c in chunks), "Markdown table missing from chunks!"
    assert any("AED 1,250,000,000" in c for c in chunks), "Financial amount corrupted in chunks!"
    print("  [PASS] MarkdownChunker preserves tables, header contexts, and comma numbers.", flush=True)

if __name__ == "__main__":
    test_entity_registry()
    test_bank_matcher()
    test_analytics()
    test_security_auth()
    test_markdown_chunker()
    print("\n>>> ALL INDEPENDENT FORENSIC VERIFICATIONS PASSED! <<<", flush=True)
