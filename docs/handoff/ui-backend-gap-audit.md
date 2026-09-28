> Archived design input (Sept 2026). The implemented contract lives in code — see ../../HANDOFF.md §2. Line numbers refer to the pre-change code at 681d5ab.

# UI ↔ Backend gap spec (from audit; line numbers are approximate — re-locate by reading the code)

Alembic head: c7d8e9f0a1b2. NONE of the items below needs a migration (reuse existing tables/JSON columns).

## Backend facts
- PUT /settings: gini_tolerance, psi_warning_threshold, psi_breach_threshold used by services/analytics/policy_checker.py only at upload time. min_observation_months used only as label text in api/models.py compare data_config. auto_mask_* / strict_zero_trust are ignored by everything.
- Notifications: nothing ever inserts Notification rows (ORM attribute is `type`, column notification_type).
- Global search (api/system.py): ILIKE over Model.name/description and RegulatoryStandard.title only.
- /users/me GET only; nothing writes full_name/title/division/security_clearance.
- Export: GET /models/{id}/export-data returns JSON {model_info, history}; no PDF/DOCX.
- Chat: POST /query persists chat_sessions/chat_messages (sources_json) but no read endpoint. Suggested actions are a fixed list (api/query.py ~212-216).
- Gap analysis: POST /gap-analysis result not persisted.
- Model versions: no endpoint creates a 2nd ModelVersion.
- SECURITY: GET /privacy/redactions has no ownership check (returns raw→token map for any session UUID). /query session reuse only checks tenant, not user.

## Existing tables
- users: full_name, title, division, security_clearance, role, ...
- tenant_settings: gini_tolerance, psi_warning_threshold, psi_breach_threshold, auto_mask_*, strict_zero_trust, min_observation_months
- notifications: id, tenant_id, user_id, model_id (nullable), title, description, notification_type (ORM attr `type`) PASS/WARNING/BREACH/INFO, is_read, created_at
- regulatory_standards: code, title, authority, jurisdiction, clauses_json, effective_date, category, description
- models: tenant_id, user_id, name, model_type, description, portfolio, algorithm, status (nullable PASS/WARNING/BREACH)
- model_versions: model_id, version, is_current, parent_version_id, metrics (ModelValidationProfile dump), gap_analysis (BreachReport dump {results:[{metric_name,value,threshold,status,rule_basis}]}), population_deciles
- documents: tenant_id, user_id, model_version_id, filename, file_type, upload_time, raw_markdown, status PROCESSING/READY/ERROR, metadata_json {profile, breach_report, ews_report}
- chat_sessions: tenant_id, user_id, model_version_id (nullable); chat_messages: session_id, role, content, sources_json [{source, section, text, score, retrieval_method}], created_at

## WIRE checklist
- W1 Notifications. Backend api/documents.py upload_document: after parent_model.status is set and before commit, db.add(Notification(tenant_id, user_id=current_user.sub, model_id=model_version.model_id, title=f"{parent_model.name}: {computed_status.value}", description=f"{safe_filename}: {num_breaches} breach / {num_warnings} warning / {num_passes} pass", type=NotificationTypeEnum(computed_status.value))). Optionally in except branches after rollback add an INFO/BREACH "processing failed" notification with own commit. Frontend: App.tsx loads listNotifications() in initial effect and after uploads; keep unreadCount; pass to TopNav; TopNav bell dot only when unreadCount>0; NotificationsDrawer onRead callback decrements.
- W2 AI Reviews KPI. schemas/system.py DashboardMetricsResponse add ai_reviews:int=0; api/system.py get_dashboard_metrics counts ChatMessage join ChatSession where tenant and role==ASSISTANT. Frontend adapters.ts toDashboardMetrics aiReviews: dto.ai_reviews ?? 0; OverviewView shows 0 not "—".
- W3 Scope AI Analyst chat to the model. schemas/query.py QueryRequest add model_version_id: Optional[UUID]=None. api/query.py: when document_id absent and model_version_id given, validate version belongs to tenant (join Model), pick latest Document with that model_version_id, tenant, status==READY order by upload_time desc; use doc.id in retriever.retrieve; set ChatSession.model_version_id; require ChatSession.user_id == current_user.sub when reusing a session. Frontend sse.ts add modelVersionId → model_version_id; WorkspaceView passes modelVersionId: currentModel.currentVersionId, documentId: activeDocumentId ?? undefined; App.tsx add key={currentModel.id} to <WorkspaceView>.
- W4 Chat history reload. Backend api/query.py: GET /query/sessions?model_version_id= (current user+tenant sessions, newest first; include id, model_version_id, created_at, message_count, last_message_preview) and GET /query/sessions/{session_id}/messages (ownership check) returning [{id, role, content, sources_json, created_at}]. DTOs in schemas/query.py. Frontend api.ts listChatSessions, getChatMessages; WorkspaceView on mount loads latest session for currentVersionId and hydrates messages+sessionId.
- W5 Privacy Inspector redaction log. Backend api/privacy.py get_redactions: add db dep, 404 unless ChatSession exists with id==session_id, tenant==current tenant, user_id==current_user.sub (security fix). Frontend: WorkspaceView onSessionIdChange prop; App holds chatSessionId; when privacy inspector opens call getRedactions(chatSessionId) → redactionsToEntities → setRedactedEntities. adapters.ts map `[GPE` to LOCATION. PrivacyInspectorDrawer unique key (`${masked}|${raw}|${idx}`).
- W6 Threshold settings take effect. Backend api/system.py update_tenant_settings: after applying fields, load tenant models with selectinload(Model.versions); for each current version with metrics run PolicyChecker().check(ModelValidationProfile.model_validate(v.metrics), settings), set v.gap_analysis = report.model_dump(), recompute Model.status (extract the status rule from documents.py into a shared helper in policy_checker.py and use it in both places). Commit once. Frontend: SettingsView onSaved prop; App factors initial load into reload() (settings, models, dashboard, notifications) and passes it. Fix Gini copy in SettingsView to describe the 40%→40%+tolerance warning band.
- W7 Metric cards follow backend policy results (frontend only). adapters.ts toModelSummary keeps policyResults (metric_name, value, threshold, status) from current_version.gap_analysis.results and stops using GINI_TARGET/AUC_BENCHMARK/KS_BENCHMARK for status. WorkspaceView metric cards take tone+threshold from results for "Gini Coefficient","AUC","KS Statistic","PSI" (check exact metric_name strings in backend policy_checker.py); "Not reported" when missing. Delete metricTone. Fix "Breach threshold" label (it shows the warning threshold). Gap tab shows value and threshold.
- W8 Fix model compare. backend api/models.py compare_models: build separate baseline_metrics (baseline values, is_diff False) and challenger_metrics; use respectively. _fmt: normalise Gini and KS (absolute and <=1 → ×100) using metric unit like policy_checker.get_normalized_value.
- W9 Persist LLM gap analysis + refresh after upload. Backend api/gap_analysis.py: after output guardrails pass, doc.metadata_json = {**(doc.metadata_json or {}), "llm_gap_analysis": response.model_dump(mode="json")}; commit (reassign dict). Frontend RegulatoryLibraryView: wrap runGapAnalysis in its own try/catch (non-fatal); then fresh = await getModel(selectedModelId); pass toModelSummary(fresh, settings) via onAnalyzeDocument. App handleDocumentAnalyzed replaces model in list, sets currentModel, calls reload(). Workspace Gap tab: fetch latest document detail and render metrics_summary.llm_gap_analysis.gaps[] (+coverage_score) if present (check GET /documents/{id} response shape and GapAnalysisResponse schema).
- W10 "Run Gap Analysis" quick action in WorkspaceView calls api.runGapAnalysis(latestDocIdForVersion) then switches to gap tab (show loading/error).
- W11 Citation navigation (frontend). ChatSource add text, score; keep them from SSE citations; render snippet in Citations tab. App onOpenRegulatoryStandard=(code)=>{setLibraryFocus(code); setActiveNav('library')}; RegulatoryLibraryView focusQuery prop pre-fills question and expands matching standard. Sources starting with doc- or equal to a document filename → switch workspace tab to documents with that document selected.
- W12 Global search. Backend api/system.py: ILIKE on RegulatoryStandard.title, code, description (code as description); tenant-scoped Document.filename matches as type="document" (id = document id, include model id via ModelVersion if cheap). Frontend types SearchResult.type add 'document'; TopNav standard & document results clickable via onOpenStandard/onOpenDocument props wired in App; models missing in local list fetched via getModel rather than dropped; placeholder "Search models, standards, documents…".
- W13 Profile edit. Backend schemas/system.py UserProfileUpdate(full_name,title,division all optional, max lengths); api/system.py PATCH /users/me applying exclude_unset; role & security_clearance not editable. Frontend api.ts updateUserProfile; ProfileModal edit form + Save; useAuth exposes refreshUser if needed.
- W14 Export options. Backend export_model_data: query params include_citations, include_audit_trail (bools, default false); ModelExportData add optional documents (DocumentMetadata-like list for all model versions) when include_audit_trail, and chat_citations (sources_json of assistant messages from sessions whose model_version_id in versions) when include_citations. Frontend getModelExport(id, opts); ExportReportModal fetches with flags at download time; drop export_options stub.
- W15 Model versions. Backend POST /models/{model_id}/versions body {version}; tenant check; unique version per model (409); prev current is_current=False; new version parent_version_id=prev.id, is_current=True; ModelVersionCreate schema. Frontend api.ts createModelVersion; "New version" action in ModelLineageModal (then refresh); fix Gini label in ModelLineageModal using adapters getMetricValue.
- W16 Honest status/KPIs (frontend). null status → 'PENDING' (add to ModelStatus type + style maps in TopNav, OverviewView, WorkspaceView). OverviewView "100% compliant baseline" → computed round((active − issues)/active×100)% guarded.
- W17 App refresh + new-audit robustness (frontend). reload() after audit created / doc analyzed; render TopNav without a model (currentModel optional); NewAuditModal: if upload fails after createModel succeeded still call onAuditCreated and show error; reset form after success; pass settings to toModelSummary.
- W18 Real "last analyzed". Backend schemas/models.py ModelSummary add last_analyzed_at: Optional[datetime]; list_models/get_model fill from max(Document.upload_time) where tenant & READY grouped by model_version_id (for current version). Frontend adapters use it.

## REMOVE checklist (frontend)
- R1 SideNav storage widget ("Audit Storage 72%") + HardDrive import.
- R2 OverviewView "Zero PII leaks detected" → neutral text.
- R3 ExportReportModal "Export Format" block (disabled PDF/DOCX + no-op JSON button + note). Keep Download JSON. Update HelpModal sentence about PDF/DOCX.
- R4 Recommended-actions chips in WorkspaceView + pendingActions/suggestedActions state, sse.ts suggestedActions handling, types.ts field. Backend: remove the fixed suggestedActions emission in api/query.py.
- R5 Synthetic ROC chart in WorkspaceView (+ rocPoints, plot helpers, aucToRoc import); delete frontend/src/lib/roc.ts and RocPoint type; make grid single column.
- R6 Masking toggles in SettingsView + ToggleRow; drop auto_mask_*/strict_zero_trust from payload, TenantSettings type, toSettings. Replace with a read-only "Always enforced" panel (bank, org, person, location, email, phone; egress validation hard-blocks leaks). Backend columns stay.
- R7 Min observation window setting (SettingsView + payload + types + adapters) and CompareModelsView "Data Configuration" block; backend compare data_config → "".
- R8 RegulatoryLibraryView "Active Framework" badge; copy → "Reference catalog of supervisory standards".
- R9 ProfileModal Security Clearance row + 'Risk Management' fallback.
- R10 adapters: drop "• Production" suffix → "Version X (current)".
- R11 CompareModelsView "N resolved" → "N fewer open findings than baseline".
- R12 api.ts dead code: delete login/register/refreshToken (duplicated in useAuth/http). Add a Delete button in DocumentViewer using deleteDocument (backend works) with confirm.
- R13 Copy fixes: SettingsView "reporting formats"; HelpModal "Initiate New Model Audit" → "New Audit"; HelpModal/Workspace chat copy accurate after W3.
- Also: DocumentCompareView fires an LLM comparison on mount and on every picker change → replace with an explicit "Compare" button.

## FROZEN API CONTRACT (backend implements exactly; frontend codes against exactly)
All endpoints require Bearer auth and are tenant-scoped. JSON field names are snake_case.

1. GET /dashboard/metrics → {active_models:int, documents_analyzed:int, compliance_issues:int, ai_reviews:int}
2. POST /query (SSE, existing) request body gains optional `model_version_id: uuid|null`. Existing SSE events unchanged EXCEPT the `suggestedActions` event is no longer emitted (R4).
3. GET /query/sessions?model_version_id=<uuid optional> → [{id:uuid, model_version_id:uuid|null, created_at:iso, message_count:int, last_message_preview:str|null}] newest first; only current user's sessions in tenant.
4. GET /query/sessions/{session_id}/messages → [{id:uuid, role:"user"|"assistant", content:str, sources_json:[{source,section,text,score,retrieval_method}]|null, created_at:iso}] oldest first; 404 if not the current user's session.
5. GET /privacy/redactions?session_id=<uuid> → unchanged response shape; now 404 unless session belongs to current user+tenant.
6. PUT /settings → unchanged shape; side effect: re-evaluates every model's current version against the new thresholds (updates model_versions.gap_analysis and models.status).
7. GET /search?q= → {results:[{id:uuid, type:"model"|"regulatory_standard"|"document", title:str, description:str|null, model_id:uuid|null}]}. For documents: id=document id, title=filename, description="Document", model_id=owning model id. For standards: title=title, description=code. For models: model_id=id.
8. PATCH /users/me body {full_name?:str|null, title?:str|null, division?:str|null} (each ≤120 chars) → UserProfileResponse (same as GET /users/me).
9. GET /models/{id}/export-data?include_citations=bool&include_audit_trail=bool → existing {model_info, history} plus `documents: [{id, filename, file_type, upload_time, status, model_version_id}] | null` (present only when include_audit_trail) and `chat_citations: [{session_id, message_id, created_at, sources:[...]}] | null` (only when include_citations).
10. POST /models/{model_id}/versions body {version:str (1..32 chars)} → 201 ModelVersionDTO {id, model_id, version, is_current, parent_version_id, metrics, gap_analysis, population_deciles, created_at}; 409 if version string already exists for the model; 404 if model not in tenant. New version becomes current (is_current true, previous false), metrics/gap_analysis/population_deciles start null.
11. GET /models and GET /models/{id} → ModelSummary gains `last_analyzed_at: iso|null` (max upload_time of READY documents attached to the current version).
12. POST /models/compare → baseline card metrics now show baseline values (old/new diff only on challenger card); Gini/KS values normalised to percentage strings; data_config becomes "".
13. POST /gap-analysis → unchanged response {gaps:[{requirement,status,description,recommendation}], coverage_score}; side effect persists it into documents.metadata_json.llm_gap_analysis, so GET /documents/{id} → metrics_summary.llm_gap_analysis has the same shape.
14. Notifications (GET /notifications) now get populated: one per successful document upload (type = computed model status PASS/WARNING/BREACH, model_id set) and an INFO one on processing failure.
