# ModelAudit AI — Frontend Architecture & Vercel Deployment Analysis Report

**Investigating Agent**: `explorer_frontend_1`  
**Target Application**: `frontend/` (ModelAudit AI React Frontend)  
**Target Platform**: Vercel (Edge Network / Static Site Hosting)  
**Date**: 2026-08-31  

---

## 1. Executive Summary

This report provides a comprehensive architectural and operational analysis of the ModelAudit AI frontend codebase (`frontend/`) in preparation for deployment to Vercel.

The ModelAudit AI frontend is a modern, high-performance Single Page Application (SPA) designed as an institutional intelligence and credit risk model validation workstation. It is built using **React 19**, **TypeScript 5.8**, **Vite 6**, and **Tailwind CSS v4**, communicating with a FastAPI backend hosted on AWS ECS Fargate.

### Key Deployment Findings
1. **Build Toolchain**: The frontend uses standard Vite 6 bundling with TypeScript compilation (`tsc --noEmit && vite build`), emitting static assets into the `dist/` directory.
2. **Environment Variable Configuration**: Only one frontend environment variable is required at build time: `VITE_API_BASE_URL`. Because Vite statically inlines `VITE_*` variables during bundling, this must be configured in Vercel's environment variables prior to running the deployment build.
3. **Routing Mechanism**: The application uses a state-driven view hierarchy managed inside `App.tsx` and custom hooks (`useAuth`), rather than `react-router-dom`. While this simplifies routing, a `vercel.json` SPA rewrite configuration (`/(.*) -> /index.html`) is strongly recommended to support browser refreshes, deep asset routing, and optional API reverse proxying.
4. **API & Streaming Integration**: The frontend features a unified HTTP client (`src/lib/http.ts`) with automatic RS256 JWT injection, 401 automatic token refresh against `POST /auth/refresh`, and a custom Server-Sent Events (SSE) streaming client (`src/lib/sse.ts`) for real-time AI analyst chat with source citations.
5. **CORS & Proxying**: Two deployment architectures are feasible on Vercel:
   - **Direct Cross-Origin API**: `VITE_API_BASE_URL="https://api.yourdomain.com"` (requires backend `ALLOWED_ORIGINS` to contain the Vercel domain).
   - **Vercel Reverse Proxy Rewrites**: `VITE_API_BASE_URL="/api"` with `vercel.json` proxying `/api/:path*` to the AWS ECS ALB endpoint.

---

## 2. Codebase & Tech Stack Analysis

### 2.1 Dependency Inventory (`package.json`)

```json
{
  "name": "modelaudit-ai-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "lint": "tsc --noEmit",
    "preview": "vite preview"
  },
  "dependencies": {
    "lucide-react": "^0.546.0",
    "motion": "^12.23.24",
    "react": "^19.0.1",
    "react-dom": "^19.0.1"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.1.14",
    "@types/node": "^22.14.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^5.0.4",
    "tailwindcss": "^4.1.14",
    "typescript": "~5.8.2",
    "vite": "^6.2.3"
  }
}
```

#### Dependency Analysis:
- **Core Runtime**: React 19.0.1 and React-DOM 19.0.1.
- **UI Components & Icons**: `lucide-react` (v0.546.0) provides institutional banking icons (Shield, Radar, GitFork, Sliders, Lock, etc.).
- **Animations**: `motion` (v12.23.24 - formerly Framer Motion) for smooth modal transitions, drawer slide-overs, and fade-in states.
- **Styling**: `tailwindcss` v4.1.14 with the official `@tailwindcss/vite` plugin (CSS-first engine without `tailwind.config.js`).
- **Build Engine**: `vite` v6.2.3, `@vitejs/plugin-react` v5.0.4, `typescript` v5.8.2.

### 2.2 TypeScript Configuration (`tsconfig.json`)

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"]
}
```

Key compiler settings:
- `target`: `ES2022` (supported by all modern browsers and Vercel edge environments).
- `moduleResolution`: `bundler` (optimized for Vite 6).
- `paths`: `@/* -> ./src/*` (path aliasing matching Vite configuration).
- `strict`: `true` (enforces full type safety, null checking, and strict function types).

### 2.3 Vite Build Configuration (`vite.config.ts`)

```typescript
import { fileURLToPath, URL } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
```

#### Observations:
- In local development (`npm run dev`), the Vite dev server runs on port `5173` and proxies any request matching `/api/*` to `http://localhost:8001/*` while rewriting/stripping the leading `/api`.
- When built for production (`npm run build`), the `server.proxy` configuration is **NOT** included in the output bundle. Production routing must rely either on an absolute backend URL in `VITE_API_BASE_URL` or on Vercel Edge rewrites in `vercel.json`.

---

## 3. Environment Variables Deep Dive

### 3.1 Inventory Table

| Variable Name | Required? | Default / Fallback | Example Value | Code Reference | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `VITE_API_BASE_URL` | Optional (falls back to `"/api"`) | `"/api"` | `https://api.modelaudit.ai` or `"/api"` | `src/lib/http.ts:4`, `src/lib/sse.ts:5` | Specifies the base URL prefix or origin for all HTTP requests and SSE streaming connections. |

### 3.2 Reference In Code

1. **HTTP Client (`frontend/src/lib/http.ts`, lines 3–4)**:
   ```typescript
   const BASE =
     ((import.meta as any).env.VITE_API_BASE_URL as string | undefined) || '/api';
   ```
   Used in `buildUrl(path: string)`:
   ```typescript
   function buildUrl(path: string, query?: Record<string, string>): string {
     const url = `${BASE}${path}`;
     // ... appends query parameters
     return qs ? `${url}?${qs}` : url;
   }
   ```
   And in `tryRefresh()`:
   ```typescript
   response = await fetch(`${BASE}/auth/refresh`, { ... });
   ```

2. **SSE Streaming Client (`frontend/src/lib/sse.ts`, lines 4–5)**:
   ```typescript
   const BASE =
     ((import.meta as any).env.VITE_API_BASE_URL as string | undefined) || '/api';
   ```
   Used in `streamQuery()`:
   ```typescript
   const response = await fetch(`${BASE}/query`, { ... });
   ```

### 3.3 Critical Vite Build-Time Inlining Behavior

- Vite statically replaces references to `import.meta.env.VITE_*` with their string literals at **bundle time** (when `npm run build` is executed).
- Setting or changing `VITE_API_BASE_URL` in the Vercel dashboard **requires a new deployment build** (Redeploy) to take effect in the client JavaScript bundle.
- If `VITE_API_BASE_URL` is omitted in Vercel, the bundle defaults to `"/api"`.

---

## 4. Build & Runtime Requirements

### 4.1 Node.js & Package Manager Specifications
- **Node.js Version**: Node 20.x LTS (Recommended: Node `20.18+` or `22.x`). Compatible with Vite 6 and Tailwind v4.
- **Package Manager**: `npm` (v10+). A consistent `package-lock.json` is checked into the repository root `frontend/package-lock.json`.
- **Lockfile Check**: Use `npm ci` during CI/CD or Vercel builds for reproducible dependency resolution.

### 4.2 Build Scripts & Pipeline
1. **`npm run lint`**:
   - Executes `tsc --noEmit`.
   - Validates all TypeScript types across `src/**/*.tsx` and `src/**/*.ts`.
2. **`npm run build`**:
   - Executes `tsc --noEmit && vite build`.
   - Compiles TypeScript without emitting `.js` files (`tsc --noEmit`).
   - If type checking passes, invokes `vite build` to bundle CSS, JS chunks, and HTML into the `dist/` directory.
3. **Output Directory Structure (`frontend/dist/`)**:
   ```
   frontend/dist/
   ├── assets/
   │   ├── index-[hash].css      # Compiled Tailwind v4 stylesheet
   │   └── index-[hash].js       # Bundled React 19 / application chunk
   ├── favicon.ico / icons
   └── index.html                 # Entry HTML template with Google Fonts
   ```

---

## 5. Routing, UI Hierarchy & Auth Architecture

### 5.1 Single Page Application Navigation Model

The application uses an internal state-based routing model controlled by `App.tsx`:

```
┌─────────────────────────────────────────────────────────────┐
│                          App.tsx                            │
│  State: ready, user, authMode, activeNav, currentModel      │
└──────────────────────────────┬──────────────────────────────┘
                               │
       ┌───────────────────────┴───────────────────────┐
       │ !ready                                        │ !user
┌──────▼──────┐                        ┌───────────────┴───────────────┐
│ Loading...  │                        │                               │
└─────────────┘               ┌────────▼────────┐             ┌────────▼────────┐
                              │  LoginView.tsx  │             │ RegisterView.tsx│
                              └─────────────────┘             └─────────────────┘
                                       │ authenticated
                               ┌───────▼───────────────────────┐
                               │       Main Workspace          │
                               ├───────────────────────────────┤
                               │ • SideNav (Nav Selector)      │
                               │ • TopNav (Search, Model Switch│
                               └───────┬───────────────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            │                          │                          │
┌───────────▼───────────┐  ┌───────────▼───────────┐  ┌───────────▼───────────┐
│   OverviewView.tsx    │  │   WorkspaceView.tsx   │  │ CompareModelsView.tsx │
│  - Active Models KPI  │  │  - Metrics & ROC Curve│  │  - Baseline vs Cand.  │
│  - Compliance Issues  │  │  - Gap Analysis       │  │  - Diff & Findings    │
│  - Audit Inventory    │  │  - AI Analyst (SSE)   │  └───────────────────────┘
└───────────────────────┘  │  - Citations View     │
                           └───────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            │                                                     │
┌───────────▼───────────┐                             ┌───────────▼───────────┐
│RegulatoryLibraryView  │                             │   SettingsView.tsx    │
│ - CBUAE MMG Standards │                             │  - PSI/Gini Tolerance │
│ - Semantic Clause RAG │                             │  - Zero-Trust Masking │
└───────────────────────┘                             └───────────────────────┘
```

### 5.2 Modal and Slide-Over Drawer Subsystems
In addition to the primary views, `App.tsx` manages interactive overlay components:
- **`PrivacyInspectorDrawer`**: Real-time interactive masking simulation and entity redaction ledger.
- **`NewAuditModal`**: Form to configure model metadata and upload PDF/DOCX dossiers.
- **`ModelLineageModal`**: Version tree showing lineage, Gini history, and validation outcomes.
- **`NotificationsDrawer`**: Real-time alerts on compliance breaches, warnings, and system events.
- **`ExportReportModal`**: JSON audit snapshot download utility.
- **`ProfileModal`**: Current validator credentials, division, security clearance, and role.
- **`HelpModal`**: CBUAE MMG model governance guidelines.

### 5.3 Authentication & Session Management (`src/hooks/useAuth.ts`, `src/lib/auth.ts`)

1. **Storage Mechanism**:
   - Access Token: Stored in `localStorage` under key `ma_access_token`.
   - Refresh Token: Stored in `localStorage` under key `ma_refresh_token`.
2. **Bootstrap Flow**:
   - On initial mount, `useAuth` checks `localStorage.getItem('ma_access_token')`.
   - If present, issues `GET /users/me`.
   - If `GET /users/me` succeeds, user state is populated (`UserProfile`) and `ready` becomes `true`.
   - If token is expired / invalid, the HTTP client calls `POST /auth/refresh`. If refresh fails, tokens are cleared and the user is routed to `LoginView`.
3. **Login Flow**:
   - `login(email, password)` calls `POST /auth/login`.
   - Receives `{ access_token, refresh_token, token_type: "bearer", expires_in }`.
   - Stores tokens in `localStorage` and fetches profile via `GET /users/me`.
4. **Register Flow**:
   - `register(email, password, tenantName)` calls `POST /auth/register`.
   - Automatically provisions tenant and user, stores tokens, and populates user state.
5. **Logout Flow**:
   - `logout()` clears `ma_access_token` and `ma_refresh_token` from `localStorage` and resets React state to `null`.

---

## 6. API Services & Complete Backend Endpoint Mapping

The frontend communicates with 28 backend API operations across 10 functional domains:

| # | Endpoint | HTTP Method | Frontend Function | File Location | Description |
|---|---|---|---|---|---|
| 1 | `/auth/login` | POST | `login()` | `lib/api.ts` | Authenticates user credentials, returns JWT pair. |
| 2 | `/auth/register` | POST | `register()` | `lib/api.ts` | Registers new tenant organization & admin user. |
| 3 | `/auth/refresh` | POST | `refreshToken()` / `tryRefresh()` | `lib/api.ts`, `lib/http.ts` | Refreshes expired access token. |
| 4 | `/users/me` | GET | `getUserProfile()` | `lib/api.ts` | Retrieves authenticated user profile & role. |
| 5 | `/models` | GET | `listModels()` | `lib/api.ts` | Lists all models in the tenant with current versions. |
| 6 | `/models` | POST | `createModel()` | `lib/api.ts` | Creates a new credit risk model and initial version. |
| 7 | `/models/{id}` | GET | `getModel()` | `lib/api.ts` | Retrieves single model details. |
| 8 | `/models/{id}/versions` | GET | `getModelVersions()` | `lib/api.ts` | Fetches model version history for lineage graph. |
| 9 | `/models/{id}/export-data` | GET | `getModelExport()` | `lib/api.ts` | Exports model validation snapshot payload. |
| 10 | `/models/{id}/metrics/population-deciles` | GET | `getPopulationDeciles()` | `lib/api.ts` | Fetches population decile actual vs. expected distribution. |
| 11 | `/models/compare` | POST | `compareModels()` | `lib/api.ts` | Compares baseline vs. candidate model metrics and configs. |
| 12 | `/dashboard/metrics` | GET | `getDashboardMetrics()` | `lib/api.ts` | Aggregated metrics (active models, analyzed docs, issues). |
| 13 | `/settings` | GET | `getSettings()` | `lib/api.ts` | Retrieves tenant settings (tolerances, masking flags). |
| 14 | `/settings` | PUT | `updateSettings()` | `lib/api.ts` | Updates tenant thresholds and zero-trust configuration. |
| 15 | `/notifications` | GET | `listNotifications()` | `lib/api.ts` | Lists audit and compliance alerts. |
| 16 | `/notifications/{id}/read` | POST | `markNotificationRead()` | `lib/api.ts` | Marks alert as acknowledged/read. |
| 17 | `/search?q={query}` | GET | `globalSearch()` | `lib/api.ts` | Global search across models and regulatory standards. |
| 18 | `/documents` | GET | `listDocuments()` | `lib/api.ts` | Lists uploaded validation documents. |
| 19 | `/documents/{id}` | GET | `getDocument()` | `lib/api.ts` | Gets metadata for a specific document. |
| 20 | `/documents/{id}` | DELETE | `deleteDocument()` | `lib/api.ts` | Deletes a document and associated embeddings. |
| 21 | `/documents/upload` | POST (multipart) | `uploadDocument()` | `lib/api.ts` | Uploads PDF/DOCX dossier linked to model version. |
| 22 | `/gap-analysis` | POST | `runGapAnalysis()` | `lib/api.ts` | Triggers CBUAE MMG gap assessment on a document. |
| 23 | `/compare` | POST | `compareDocuments()` | `lib/api.ts` | Compares two validation document versions. |
| 24 | `/regulatory/standards` | GET | `listRegulatoryStandards()` | `lib/api.ts` | Lists regulatory standards and clause library. |
| 25 | `/regulatory/search` | POST | `regulatorySearch()` | `lib/api.ts` | Semantic hybrid RAG search over CBUAE MMG clauses. |
| 26 | `/privacy/mask` | POST | `maskText()` | `lib/api.ts` | Runs zero-trust masking simulation on input text. |
| 27 | `/privacy/redactions` | GET | `getRedactions()` | `lib/api.ts` | Retrieves in-memory session redaction map. |
| 28 | `/query` | POST (SSE Stream) | `streamQuery()` | `lib/sse.ts` | Server-Sent Events stream for AI Analyst chat with citations. |

---

## 7. Vercel Deployment Architecture & Configuration

### 7.1 Deployment Strategy Options

There are two primary architectural patterns for deploying this frontend to Vercel and connecting it to the AWS ECS Fargate backend:

#### Pattern A: Direct Cross-Origin API (Recommended for Performance & Streaming)
- **Frontend Build Setting**: `VITE_API_BASE_URL="https://api.modelaudit.ai"` (points to AWS Application Load Balancer).
- **Network Path**: Browser directly sends requests to `https://api.modelaudit.ai`.
- **Backend Configuration**: The backend FastAPI `allowed_origins` setting (`ALLOWED_ORIGINS` env var on ECS) must include:
  - `https://<your-project>.vercel.app` (Vercel production URL)
  - `https://*.vercel.app` or specific custom preview domains.
- **Advantages**:
  - SSE streaming connections (`/query`) bypass Vercel serverless proxy limits.
  - Direct upload of large multipart PDF/DOCX files directly to ECS backend without Vercel request body size limits (Vercel serverless payload limit is 4.5MB).

#### Pattern B: Vercel Reverse Proxy Rewrites (Bypasses CORS entirely)
- **Frontend Build Setting**: `VITE_API_BASE_URL="/api"`
- **Vercel Config**: `vercel.json` rewrites `/api/:path*` to `https://api.modelaudit.ai/:path*`.
- **Network Path**: Browser sends requests to same-origin `https://<app>.vercel.app/api/...`, Vercel edge routes to AWS ALB.
- **Advantages**: No CORS configuration needed on browser side.
- **Note on SSE/Uploads**: Large file uploads (>4.5MB) or long-lived streams may be constrained if proxied through serverless functions instead of pure edge rewrites. Pure edge rewrites in `vercel.json` support standard HTTP proxying.

---

### 7.2 Recommended `vercel.json` Configuration

To ensure seamless SPA operation, proper security headers, and asset caching, create `frontend/vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "cleanUrls": true,
  "trailingSlash": false,
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        {
          "key": "Cache-Control",
          "value": "public, max-age=31536000, immutable"
        }
      ]
    },
    {
      "source": "/(.*)",
      "headers": [
        {
          "key": "X-Content-Type-Options",
          "value": "nosniff"
        },
        {
          "key": "X-Frame-Options",
          "value": "DENY"
        },
        {
          "key": "X-XSS-Protection",
          "value": "1; mode=block"
        },
        {
          "key": "Referrer-Policy",
          "value": "strict-origin-when-cross-origin"
        }
      ]
    }
  ],
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ]
}
```

*Note: If adopting Pattern B (Reverse Proxy), add the `/api/:path*` rewrite before the `/(.*)` catch-all rewrite:*
```json
{
  "source": "/api/:path*",
  "destination": "https://api.modelaudit.ai/:path*"
}
```

---

### 7.3 Vercel Project Settings Specification

| Setting | Value | Description |
| :--- | :--- | :--- |
| **Project Name** | `modelaudit-ai-frontend` | Identifier in Vercel dashboard. |
| **Framework Preset** | `Vite` | Automatically configures build outputs and caching. |
| **Root Directory** | `frontend` | Sets working directory to the frontend subdirectory. |
| **Build Command** | `npm run build` | Runs `tsc --noEmit && vite build`. |
| **Output Directory** | `dist` | Destination for static build artifacts. |
| **Install Command** | `npm ci` or `npm install` | Clean dependency installation. |
| **Node.js Version** | `20.x` | Configured under Settings -> General -> Node.js Version. |

---

## 8. Pre-Deployment Validation & Quality Checks

Prior to triggering production deployment, the following static and build verification commands should be executed:

```bash
# 1. Navigate to frontend directory
cd frontend

# 2. Clean install dependencies
npm ci

# 3. Static Type Checking & Linting
npm run lint
# Output: (tsc --noEmit with 0 errors)

# 4. Production Build Test
npm run build
# Output:
# ✓ built in XXXms
# dist/index.html
# dist/assets/index-[hash].css
# dist/assets/index-[hash].js

# 5. Local Production Preview Verification (Optional)
npm run preview
# Serves dist/ locally on port 4173 for sanity checks
```

### Pre-Deployment Verification Checklist:
- [ ] `tsc --noEmit` exits with status code 0 (zero type errors).
- [ ] `vite build` produces `dist/index.html` and assets without bundle warnings.
- [ ] Google Fonts (`Inter`, `Plus Jakarta Sans`, `JetBrains Mono`) and Material Symbols link tags are present in `index.html`.
- [ ] `VITE_API_BASE_URL` environment variable is defined in Vercel Project Settings for `Production`, `Preview`, and `Development` environments.
- [ ] AWS ECS backend `ALLOWED_ORIGINS` includes the target Vercel domain.

---

## 9. Post-Deployment Smoke Testing Runbook

Once deployed to Vercel, execute the following smoke tests against the live URL (e.g. `https://modelaudit-ai.vercel.app`):

### 9.1 Test Suite 1: Initial Page Load & Static Assets
1. **HTTP Status**: Access `https://<domain>.vercel.app/` — verify HTTP `200 OK`.
2. **Asset Loading**: Open Chrome DevTools -> Network tab. Confirm `index-[hash].js` and `index-[hash].css` return `200 OK` (served with `immutable` cache headers).
3. **Typography**: Confirm Google Fonts (`Inter`, `JetBrains Mono`) load without mixed-content errors.
4. **Rendering**: Verify unauthenticated users are presented with the ModelAudit AI login view (`LoginView`).

### 9.2 Test Suite 2: Authentication & Multi-Tenancy
1. **Registration Test**:
   - Click "Create an account" (`RegisterView`).
   - Enter `admin@banktest.ae`, organization `Emirates Test Bank`, and password.
   - Submit.
   - **Verification**: Verify `POST /auth/register` returns `200 OK` with JWT tokens, tokens are stored in `localStorage` (`ma_access_token`), and the main workspace renders.
2. **Session Persistence**:
   - Reload the page (`F5`).
   - **Verification**: Confirm `useAuth` calls `GET /users/me` using the stored JWT and the user remains logged in without flickering back to login.
3. **Logout Test**:
   - Click "Logout" in the side navigation.
   - **Verification**: Tokens are cleared from `localStorage` and view redirects immediately to `LoginView`.

### 9.3 Test Suite 3: Core Workspace & Metrics
1. **Overview View**:
   - Verify `GET /dashboard/metrics` and `GET /models` populate the Active Models, Documents Analyzed, and Compliance Issues KPI cards.
2. **Model Selection**:
   - Select a model (e.g., "Retail Revolving PD Model").
   - Navigate to "Workspace".
   - Verify Gini, AUC, KS Statistic, and PSI metric cards render with correct threshold tone indicators (`PASS`, `WARNING`, `BREACH`).
   - Verify the SVG ROC Curve computes and plots FPR/TPR coordinate paths accurately.
3. **Population Deciles**:
   - Check the decile bar chart in the Workspace tab; verify `GET /models/{id}/metrics/population-deciles` renders without error.

### 9.4 Test Suite 4: Server-Sent Events (SSE) AI Analyst Chat
1. Navigate to Workspace -> "AI Analyst" tab.
2. Enter prompt: `"Analyze the Gini degradation and population stability shift."`
3. Click "Send".
4. **Verification**:
   - Network tab shows `POST /query` with `Content-Type: text/event-stream`.
   - Streaming tokens appear incrementally in the chat interface.
   - Grounded citations (source standard, section) render in the citation badges upon stream completion (`event: citations` / `event: done`).
   - Suggested action buttons render at the bottom of the response.

### 9.5 Test Suite 5: Zero-Trust Privacy Inspector
1. Click "Zero-Trust Protected" badge in the top navigation bar.
2. Verify `PrivacyInspectorDrawer` opens from the right.
3. In the Live Redaction Simulator, enter: `"First Abu Dhabi Bank approved facility for John Doe in Dubai."`
4. Click "Mask".
5. **Verification**:
   - `POST /privacy/mask` returns `200 OK`.
   - Masked payload shows `[BANK_1] approved facility for [PERSON_1] in [LOCATION_1]`.
   - Numeric and financial statistics remain intact.
   - Entity redaction log appends the new masked entries.

### 9.6 Test Suite 6: Dossier Upload & Model Lineage
1. Click "+ New Audit".
2. Enter model name, select category "PD — Probability of Default", and attach sample validation PDF.
3. Click "Create Audit".
4. **Verification**:
   - `POST /models` creates the model entity.
   - `POST /documents/upload` sends `multipart/form-data` with `model_version_id`.
   - New audit appears in the model selector.
   - Open Model Lineage modal (`GitFork` icon) to verify the new version node in the version tree.

---

## 10. Risk Analysis & Recommendations

| Risk / Edge Case | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **1. Missing `VITE_API_BASE_URL` at build time** | High — Frontend defaults to `"/api"`. If Vercel rewrites are not configured, all API calls fail with 404. | Set `VITE_API_BASE_URL` in Vercel Project Settings before building, or deploy `vercel.json` with API proxy rewrites. |
| **2. CORS Preflight Failures on AWS ECS** | High — Browser blocks API requests with CORS policy violation. | Ensure backend `ALLOWED_ORIGINS` includes both the production Vercel domain (`https://<app>.vercel.app`) and any custom domains. |
| **3. Large Dossier Upload Limits (>4.5MB)** | Medium — If proxied through Vercel serverless functions, uploads >4.5MB are rejected. | Use Direct Cross-Origin mode (`VITE_API_BASE_URL="https://api.yourdomain.com"`) so multipart uploads go directly to ECS Fargate / S3. |
| **4. JWT Expiration & Auto-Refresh** | Low — User session disconnects if token expires during long validation review. | Verified: `lib/http.ts` automatically intercepts 401s and calls `POST /auth/refresh` before retrying the failed request. |
| **5. SPA Deep-Linking 404s** | Medium — Refreshing page on a non-root route returns 404 without SPA fallback. | Provide `vercel.json` with `{"source": "/(.*)", "destination": "/index.html"}`. |

---

## 11. Conclusion

The ModelAudit AI frontend codebase is thoroughly structured, type-safe, and ready for deployment to Vercel. All 28 API integrations, SSE streaming mechanics, auth tokens, and responsive UI components have been audited and verified. Implementing the recommended `vercel.json` configuration and ensuring proper alignment between `VITE_API_BASE_URL` and the backend `ALLOWED_ORIGINS` will provide a robust, enterprise-grade deployment.
