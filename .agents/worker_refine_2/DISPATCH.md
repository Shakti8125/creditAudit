# DISPATCH

## 2026-08-31T17:43:41Z

Read c:\Users\Shakti\Documents\CreditAudit- AI\.agents\ORIGINAL_REQUEST.md and c:\Users\Shakti\Documents\CreditAudit- AI\.agents\AGENTS.md.
Also read the detailed audit findings from:
- c:\Users\Shakti\Documents\CreditAudit- AI\.agents\challenger_arch_1\report.md
- c:\Users\Shakti\Documents\CreditAudit- AI\.agents\challenger_arch_1\handoff.md

Your working directory is c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_refine_2/

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

CRITICAL INSTRUCTION:
DO NOT modify any existing source code files in backend/, frontend/, or deploy/.
Your sole output file to update/edit is:
`c:\Users\Shakti\Documents\CreditAudit- AI\deployment_steps.md`

Update and refine `deployment_steps.md` to incorporate the 5 architectural refinements identified during gate review:
1. **Fix Seeding Script Reference (Section 5.7 & Section 8)**:
   - Clarify that `backend/scripts/seed_regulatory_standards.py` is the built-in seed script that populates the 4 foundational standards (CBUAE MMG §4.2, IFRS 9 ECL, FRB SR 11-7, Basel III/IV) into PostgreSQL.
   - Clarify that initial demo/analyst tenant user accounts are provisioned via `POST /auth/register` (using the exact curl payload documented in Section 8.2 Step 2). Remove the standalone one-off execution of nonexistent `seed_demo_users.py` so ECS one-off tasks run flawlessly without `ModuleNotFoundError`.
2. **Dual NAT Gateway Multi-AZ HA Architecture (Section 1, 4.1, 5.1)**:
   - Document provisioning Dual NAT Gateways (one in Public Subnet AZ-a, one in Public Subnet AZ-b) with dedicated route tables for Private Subnet A and Private Subnet B. Explain how this eliminates the single point of failure (SPOF) for outbound HTTPS traffic to Upstash Redis REST, Pinecone, NVIDIA NIM, and Google Gemini.
3. **ALB Idle Timeout for LLM Streaming (Section 5.5)**:
   - Add the explicit AWS CLI command to set ALB idle timeout to 300 seconds:
     `aws elbv2 modify-load-balancer-attributes --load-balancer-arn $ALB_ARN --attributes Key=idle_timeout.timeout_seconds,Value=300`
     Explain that this ensures long-running SSE token streams on `POST /query` are never prematurely severed at the default 60s limit.
4. **Fargate Task Sizing for IBM Docling & spaCy (Section 1, 5.8, Table)**:
   - Update recommended task sizing to 1024 CPU units (1.0 vCPU) and 4096 MB RAM (4GB) in `task-definition.json` and system overview, ensuring ample memory for IBM Docling 2.0 PyMuPDF OCR extraction and spaCy `en_core_web_lg` vector processing under concurrent workloads.
5. **Security Group Creation Sequence (Section 4.1 & 5.1)**:
   - Clearly present the sequential 3-step creation flow: Create `sg-alb` -> Create `sg-ecs` (referencing `sg-alb` as source for port 8001) -> Create `sg-rds` (referencing `sg-ecs` as source for port 5432).

Write the complete refined file `c:\Users\Shakti\Documents\CreditAudit- AI\deployment_steps.md` and write your handoff report to `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_refine_2\handoff.md`.
Send a completion message back to the orchestrator when finished.
