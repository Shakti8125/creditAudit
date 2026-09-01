import asyncio
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError

def test_privacy_pipeline():
    pipeline = MaskingPipeline()
    validator = EgressValidator()
    
    test_text = (
        "On 31 December 2023, Emirates NBD and FAB approved a loan of AED 15.5 Million "
        "to Mr. John Doe, CEO of AlphaCorp. The Gini coefficient was 42% and "
        "the observed default ratio was 1.25x. John Doe can be reached at john.doe@alphacorp.com "
        "or +971-50-123-4567. Another company, AlphaCorp Holdings, was also involved. "
        "The capital adequacy ratio is 11.5%."
    )
    
    print("--- ORIGINAL TEXT ---")
    print(test_text)
    print("\n")
    
    # Masking
    masked_text, registry = pipeline.mask_document(test_text)
    print("--- MASKED TEXT ---")
    print(masked_text)
    print("\n")
    
    # Check Registry
    print("--- ENTITY REGISTRY ---")
    mapping = registry.get_mapping()
    for k, v in mapping.items():
        print(f"{v}: {k}")
    print("\n")
    
    # Validation
    try:
        report = validator.validate(masked_text, registry)
        print("--- EGRESS VALIDATION ---")
        print(f"Is Clean: {report.is_clean}")
    except EgressViolationError as e:
        print("--- EGRESS VALIDATION FAILED ---")
        print(str(e))
        print("Violations:", e.report.violations)
        
    print("\n")
    
    # Unmasking
    unmasked_text = registry.unmask_text(masked_text)
    print("--- UNMASKED TEXT ---")
    print(unmasked_text)
    print("\n")
    
    # Assertions
    assert "Emirates NBD" not in masked_text
    assert "FAB" not in masked_text
    assert "John Doe" not in masked_text
    assert "AlphaCorp" not in masked_text
    assert "AED 15.5 Million" in masked_text  # Preserved
    assert "42%" in masked_text               # Preserved
    assert "1.25x" in masked_text             # Preserved
    assert "31 December 2023" in masked_text  # Preserved
    assert "11.5%" in masked_text             # Preserved
    
    assert unmasked_text == test_text
    print("All assertions passed! Privacy pipeline works perfectly.")

if __name__ == "__main__":
    test_privacy_pipeline()
