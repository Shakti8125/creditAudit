import re
import json
import os
import sys

def main():
    print("==================================================================")
    print("EMPIRICAL ADVERSARIAL VALIDATION OF deployment_steps.md")
    print("==================================================================")
    
    with open("deployment_steps.md", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Check Issue 1: Seeding scripts
    print("\n--- ISSUE 1: Seeding Script References ---")
    seed_demo_matches = re.findall(r"seed_demo_users", content, re.IGNORECASE)
    print(f"Occurrences of 'seed_demo_users': {len(seed_demo_matches)}")
    assert len(seed_demo_matches) == 0, "Found 'seed_demo_users' in deployment_steps.md!"
    
    all_scripts = re.findall(r"scripts\.([a-zA-Z0-9_]+)", content)
    print(f"All script module references in deployment_steps.md: {set(all_scripts)}")
    
    # Check if referenced scripts exist in backend/scripts/
    for script_name in set(all_scripts):
        script_file = os.path.join("backend", "scripts", f"{script_name}.py")
        exists = os.path.exists(script_file)
        print(f"Checking script '{script_file}': Exists? {exists}")
        assert exists, f"Referenced script {script_file} does not exist!"

    # 2. Check Issue 2: Dual NAT Gateway Multi-AZ HA Architecture
    print("\n--- ISSUE 2: Dual NAT Multi-AZ HA Architecture ---")
    nat_a_match = "NAT_GW_A" in content and "subnet-public-1a" in content
    nat_b_match = "NAT_GW_B" in content and "subnet-public-1b" in content
    rtb_a_match = "RTB_PRIVATE_A" in content and "subnet-private-1a" in content
    rtb_b_match = "RTB_PRIVATE_B" in content and "subnet-private-1b" in content
    print(f"NAT Gateway A in Public Subnet 1a configured: {nat_a_match}")
    print(f"NAT Gateway B in Public Subnet 1b configured: {nat_b_match}")
    print(f"Private Route Table A routing to NAT GW A: {rtb_a_match}")
    print(f"Private Route Table B routing to NAT GW B: {rtb_b_match}")
    assert nat_a_match and nat_b_match and rtb_a_match and rtb_b_match, "Dual NAT Multi-AZ setup incomplete!"

    # 3. Check Issue 3: ALB Idle Timeout
    print("\n--- ISSUE 3: ALB Idle Timeout for SSE ---")
    alb_timeout_found = "modify-load-balancer-attributes" in content and "Key=idle_timeout.timeout_seconds,Value=300" in content
    print(f"ALB Idle Timeout 300s command present: {alb_timeout_found}")
    assert alb_timeout_found, "ALB 300s timeout command missing!"

    # 4. Check Issue 4: Fargate Task Sizing
    print("\n--- ISSUE 4: Fargate Task Sizing ---")
    cpu_matches = re.findall(r'"cpu":\s*"(\d+)"', content)
    mem_matches = re.findall(r'"memory":\s*"(\d+)"', content)
    print(f"Task definition cpu: {cpu_matches}")
    print(f"Task definition memory: {mem_matches}")
    assert "1024" in cpu_matches, f"Expected cpu '1024', got {cpu_matches}"
    assert "4096" in mem_matches, f"Expected memory '4096', got {mem_matches}"

    # 5. Check Issue 5: Security Group Creation Sequence
    print("\n--- ISSUE 5: Security Group Creation Order ---")
    alb_sg_idx = content.find("ALB_SG_ID=$(aws ec2 create-security-group")
    ecs_sg_idx = content.find("ECS_SG_ID=$(aws ec2 create-security-group")
    rds_sg_idx = content.find("RDS_SG_ID=$(aws ec2 create-security-group")
    print(f"ALB SG creation index: {alb_sg_idx}")
    print(f"ECS SG creation index: {ecs_sg_idx}")
    print(f"RDS SG creation index: {rds_sg_idx}")
    assert 0 < alb_sg_idx < ecs_sg_idx < rds_sg_idx, "Security group creation order is incorrect!"

    # 6. Check all JSON blocks for syntactic validity
    print("\n--- JSON Blocks Validation ---")
    json_blocks = re.findall(r"```json\s*\n(.*?)\n\s*```", content, re.DOTALL)
    print(f"Found {len(json_blocks)} JSON blocks.")
    for i, raw_json in enumerate(json_blocks):
        # Substitute placeholders like <AWS_ACCOUNT_ID>, <PASSWORD>, <CERT_ID>, etc.
        sanitized = re.sub(r"<[^>]+>", "123456789012", raw_json)
        try:
            parsed = json.loads(sanitized)
            print(f"Block #{i+1}: Valid JSON. Top-level keys: {list(parsed.keys()) if isinstance(parsed, dict) else 'Array/Other'}")
        except Exception as e:
            print(f"Block #{i+1}: FAILED JSON parsing - {e}")
            raise e

    # 7. Check Environment Variables against backend/app/config.py
    print("\n--- Environment Variable Alignment Check ---")
    with open("backend/app/config.py", "r", encoding="utf-8") as f:
        config_text = f.read()

    expected_vars = [
        "DATABASE_URL", "REDIS_URL", "REDIS_TOKEN", "NVIDIA_API_KEY",
        "NVIDIA_BASE_URL", "GEMINI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX_NAME",
        "JWT_PRIVATE_KEY", "JWT_PUBLIC_KEY", "JWT_SECRET_KEY", "JWT_ALGORITHM",
        "ALLOWED_ORIGINS", "RATE_LIMIT_ENABLED"
    ]
    for var in expected_vars:
        in_guide = var in content
        print(f"Variable {var} present in deployment_steps.md: {in_guide}")
        assert in_guide, f"Variable {var} missing from deployment_steps.md!"

    print("\n==================================================================")
    print("ALL EMPIRICAL VALIDATION CHECKS PASSED PERFECTLY!")
    print("==================================================================")

if __name__ == "__main__":
    main()
