## 2026-08-28T13:51:00Z
You are a specialist Worker for ModelAudit AI Milestone 3: Document Extraction & Chunking.

# Instructions & Context
- You MUST read ORIGINAL_REQUEST.md: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\ORIGINAL_REQUEST.md`
- You MUST read the Master Bug Report: `c:\Users\Shakti\Documents\CreditAudit- AI\backend_code_audit_report.md`
- Project Identity & Rules: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\AGENTS.md`
- Domain Skills to load if needed: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\skills\p2-document-extraction\SKILL.md`
- Your working directory for agent metadata is: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_m3`

# Exclusive File Ownership
You exclusively own and may edit:
- `backend/app/services/chunker.py`
- `backend/app/services/document_extractor.py`
- `backend/app/services/__init__.py`

DO NOT edit files outside this list.

# Assigned Issues to Resolve
1. DOC-01 (Critical): In `chunker.py`, fix `_split_text` accumulation logic so `current_part` accumulates candidate snippets up to `self.chunk_size` before appending to chunks, instead of resetting on every iteration.
2. DOC-02 (Critical): In `chunker.py`, detect Markdown tables (`| ... |`) and treat table blocks as atomic chunks, exempting them from the 8-word row filter so critical financial tables are never dropped.
3. DOC-03 (High): In `chunker.py`, implement sliding window `self.overlap` logic carrying trailing context into subsequent chunks.
4. DOC-04 (High): In `chunker.py`, preserve sentence punctuation and formatting during delimiter splitting.
5. DOC-05 (Medium): In `chunker.py`, preserve double newlines (`\n\n`) for semantic paragraph splitting.
6. DOC-06 (Medium): In `document_extractor.py`, wrap `converter.convert()` with a structured `DocumentExtractionError` instead of letting raw 500 exceptions bubble up.
7. DOC-07 (Low): In `document_extractor.py`, add `InputFormat.DOCX: WordFormatOption()` to format options.
8. Re-export chunker and document extractor in `services/__init__.py`.

# MANDATORY INTEGRITY WARNING
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

# Verification & Handoff
- Verify all modified files for valid Python syntax and imports.
- Update `progress.md` in your working directory `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_m3\progress.md`.
- Write a structured handoff report in `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_m3\handoff.md`.
- Send a message to parent when completed.
