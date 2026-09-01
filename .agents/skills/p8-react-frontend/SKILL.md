---
name: p8-react-frontend
description: >-
  Use this skill to build the React frontend for ModelAudit AI Phase 8.
---
# Phase 8: React Frontend

This skill instructs you to build the React frontend. Note: detailed component design depends on Figma design (pending).

## Steps

### 1. Initialize Project
Initialize Vite + React + TypeScript project in `frontend/`:
- Run: `npm create vite@latest . -- --template react-ts`
- Install dependencies: `react-router-dom`, `axios`, `zustand` (state), `react-markdown`, `@tailwindcss/typography`
- Configure Tailwind CSS v4 or vanilla CSS with design tokens from Figma.

### 2. API Client
Create `frontend/src/api/client.ts` - Axios instance with JWT interceptor:
- Base URL from `VITE_API_URL` env var.
- Request interceptor: attach `Authorization: Bearer <token>` from localStorage.
- Response interceptor: on 401, attempt token refresh; on failure, redirect to login.

### 3. Server-Sent Events Hook
Create `frontend/src/hooks/useSSE.ts` - Custom hook for SSE:
- Accepts URL + auth token.
- Parses SSE events: `token` (append to response), `done` (close), `error` (show error).
- Returns `{ data, isStreaming, error }`.

### 4. Auth Hook
Create `frontend/src/hooks/useAuth.ts` - Auth state management:
- Login, register, logout, token refresh.
- Persist tokens in localStorage.
- Provide `isAuthenticated`, `user`, `tenant` context.

### 5. Route Pages
Create `frontend/src/pages/`:
- `LoginPage.tsx`, `RegisterPage.tsx` - Auth forms.
- `DashboardPage.tsx` - Main workspace with 7 panels.
- `ComparePage.tsx` - Document comparison view.

### 6. Core Panels
Create `frontend/src/components/` - 7 core panels (component shells, detailed design from Figma):
- `ChatPanel.tsx` - Conversation thread with SSE streaming.
- `DocumentViewer.tsx` - Uploaded document markdown rendered.
- `MetricsDashboard.tsx` - Gini/AUC/KS/PSI cards with PASS/WARNING/BREACH badges.
- `GapAnalysisPanel.tsx` - MMG compliance checklist.
- `MaskingInspector.tsx` - Entity -> token mapping table.
- `CompareView.tsx` - Side-by-side document comparison.
- `CitationsPanel.tsx` - Expandable source citation cards.

### 7. TypeScript Types
Create `frontend/src/types/` - TypeScript interfaces matching backend Pydantic schemas.

### 8. Dockerfile
Create `frontend/Dockerfile` - Multi-stage build: Node build -> Nginx serve.

### 9. Vercel Config
Create `frontend/vercel.json` - Vercel deployment config with API rewrites.

## Verification
`npm run build` succeeds. All TypeScript types compile. Login -> upload -> query flow works end-to-end.
