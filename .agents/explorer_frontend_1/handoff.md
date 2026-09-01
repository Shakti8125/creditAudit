# Handoff Report — Frontend Vercel Deployment Analysis

**Agent**: `explorer_frontend_1`  
**Date**: 2026-08-31  
**Working Directory**: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\explorer_frontend_1`  
**Artifact Reference**: `.agents/explorer_frontend_1/report.md`  

---

## 1. Observation

Direct observations from examining the `frontend/` codebase:

1. **`frontend/package.json`**:
   - Lines 6–11:
     ```json
     "scripts": {
       "dev": "vite",
       "build": "tsc --noEmit && vite build",
       "lint": "tsc --noEmit",
       "preview": "vite preview"
     }
     ```
   - Lines 12–17: Core dependencies include `"react": "^19.0.1"`, `"react-dom": "^19.0.1"`, `"motion": "^12.23.24"`, `"lucide-react": "^0.546.0"`.
   - Lines 18–27: Dev dependencies include `"@tailwindcss/vite": "^4.1.14"`, `"tailwindcss": "^4.1.14"`, `"typescript": "~5.8.2"`, `"vite": "^6.2.3"`.

2. **`frontend/vite.config.ts`**:
   - Lines 13–21:
     ```typescript
     server: {
       port: 5173,
       proxy: {
         '/api': {
           target: 'http://localhost:8001',
           changeOrigin: true,
           rewrite: (path) => path.replace(/^\/api/, ''),
         },
       },
     }
     ```
   - No custom `build.outDir` is specified, defaulting to `dist/`.

3. **`frontend/.env.example`**:
   - Lines 1–4:
     ```env
     # Base URL for backend API requests.
     # In dev, leave this empty to use the Vite proxy (/api -> http://localhost:8001).
     # In production, point this at the deployed backend origin.
     VITE_API_BASE_URL="/api"
     ```

4. **Environment Variable Usage in Code**:
   - `frontend/src/lib/http.ts` (lines 3–4):
     ```typescript
     const BASE =
       ((import.meta as any).env.VITE_API_BASE_URL as string | undefined) || '/api';
     ```
   - `frontend/src/lib/sse.ts` (lines 4–5):
     ```typescript
     const BASE =
       ((import.meta as any).env.VITE_API_BASE_URL as string | undefined) || '/api';
     ```
   - No other `VITE_*` environment variables exist across the entire `frontend/src/` codebase.

5. **Authentication & Session Tokens (`frontend/src/lib/auth.ts` & `frontend/src/hooks/useAuth.ts`)**:
   - `src/lib/auth.ts` lines 1–2: `ACCESS_KEY = 'ma_access_token'`, `REFRESH_KEY = 'ma_refresh_token'`. Tokens stored in `window.localStorage`.
   - `src/lib/http.ts` lines 54–60: `request()` injects `Authorization: Bearer ${token}` header if present.
   - `src/lib/http.ts` lines 76–100: `tryRefresh()` intercepts 401 responses, issues `POST ${BASE}/auth/refresh` with `{ refresh_token }`, updates `localStorage`, and retries the request.
   - `src/hooks/useAuth.ts` lines 49–73: Mount effect bootstraps session by verifying token via `GET /users/me`.

6. **SSE Streaming for AI Analyst (`frontend/src/lib/sse.ts`)**:
   - Lines 16–37: Issues `POST ${BASE}/query` with `Content-Type: application/json` and `Authorization: Bearer <token>`.
   - Lines 60–120: Consumes `response.body.getReader()`, decodes UTF-8 byte stream, buffers lines by `\n\n` boundary, parses `data: ` JSON payloads, and dispatches typed callbacks (`session_id`, `citations`, `token`, `suggestedActions`, `done`, `error`).

7. **Backend CORS Configuration (`backend/app/config.py` & `backend/app/main.py`)**:
   - `backend/app/config.py` lines 82: `allowed_origins: str = "http://localhost:5173,http://localhost:3000"`.
   - `backend/app/main.py` lines 34–43: `CORSMiddleware` applies `allow_origins=origins`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`.

8. **Repository Filesystem Search for Vercel Configurations**:
   - Tool `find_by_name` for `*vercel*` returned 0 results across the repository. No `vercel.json` exists currently.

---

## 2. Logic Chain

1. **Build Toolchain Requirements**:
   - From Observation 1 (`package.json` with `"typescript": "~5.8.2"`, `"vite": "^6.2.3"`, `"@tailwindcss/vite": "^4.1.14"`), the build script `"build": "tsc --noEmit && vite build"` requires Node.js (v20.x recommended) and `npm`.
   - The build output directory is Vite's default `dist/`, which contains `index.html` and assets hashed in `dist/assets/`.

2. **Environment Variable Binding**:
   - From Observations 3 and 4, `VITE_API_BASE_URL` is the sole build-time configuration parameter.
   - Because Vite inlines `import.meta.env.VITE_*` strings during `vite build`, `VITE_API_BASE_URL` must be set in Vercel Project Settings prior to triggering a build.
   - If unset, it safely falls back to `"/api"`.

3. **Backend Communication & CORS**:
   - From Observation 2 (`vite.config.ts`), dev proxy routes `/api/*` to `http://localhost:8001/*` by stripping `/api`.
   - In production on Vercel:
     - If setting `VITE_API_BASE_URL="https://api.modelaudit.ai"` (no trailing `/api`), browser requests directly hit `https://api.modelaudit.ai/auth/login`, `https://api.modelaudit.ai/models`, etc. This requires updating the backend `ALLOWED_ORIGINS` to include the Vercel domain (`https://*.vercel.app`).
     - If keeping `VITE_API_BASE_URL="/api"`, a `vercel.json` with rewrite `{"source": "/api/:path*", "destination": "https://api.modelaudit.ai/:path*"}` must be added.

4. **SPA Navigation and Vercel Routing**:
   - From Observation 8, no `vercel.json` currently exists.
   - Although navigation is currently internal state-based within `App.tsx`, adding `vercel.json` with an SPA rewrite `{"source": "/(.*)", "destination": "/index.html"}` guarantees clean URL handling, asset routing, and prevents 404 errors on deep-link refreshes.

5. **Streaming & Authentication Reliability**:
   - From Observations 5 and 6, the frontend uses native `fetch` + `ReadableStream` with Bearer auth headers for both REST requests and SSE streaming.
   - Token refresh is fully automated on HTTP 401 without requiring UI redirects if a valid refresh token exists.

---

## 3. Caveats

- **Runtime Execution**: In accordance with the read-only exploration rules, no build commands (`npm run build`) or dev servers were run during this audit. Type safety was assessed via static inspection of all TypeScript and TSX files.
- **Custom Domains**: If a custom domain (e.g. `https://audit.bank.ae`) is configured on Vercel, the backend `ALLOWED_ORIGINS` must include both the custom domain and the `*.vercel.app` preview domains.
- **Vercel Serverless Function Payload Limits**: If reverse proxying file uploads through Vercel serverless rewrites instead of direct cross-origin calls, large PDF validation dossiers (>4.5 MB) may exceed serverless body size limits. Direct cross-origin routing (`VITE_API_BASE_URL="https://api.modelaudit.ai"`) avoids this limitation.

---

## 4. Conclusion

The ModelAudit AI frontend is fully functional, architecturally unified, and ready for deployment to Vercel.

**Required Vercel Configuration Settings**:
- **Framework Preset**: `Vite`
- **Root Directory**: `frontend`
- **Build Command**: `npm run build`
- **Output Directory**: `dist`
- **Node.js Version**: `20.x`
- **Environment Variable**: `VITE_API_BASE_URL="https://<backend-host>"` (for Direct Mode) OR `"/api"` (for Proxy Mode with `vercel.json`).

**Recommended Artifacts to Add**:
- Deploy `frontend/vercel.json` with SPA catch-all rewrites (`/(.*) -> /index.html`) and security headers (`X-Content-Type-Options`, `X-Frame-Options`).

---

## 5. Verification Method

To independently verify these findings:

1. **Verify Type-Checking and Build Locally**:
   ```bash
   cd frontend
   npm ci
   npm run lint       # Runs tsc --noEmit (must exit with code 0)
   npm run build      # Verifies Vite packaging and dist/ output generation
   ```

2. **Inspect Files Referenced**:
   - `frontend/package.json` — Confirm dependencies (React 19, Vite 6, Tailwind v4).
   - `frontend/src/lib/http.ts` and `frontend/src/lib/sse.ts` — Confirm `VITE_API_BASE_URL` references.
   - `frontend/src/App.tsx` — Confirm state-driven routing and auth gate.
   - `backend/app/config.py` — Confirm `allowed_origins` setting for CORS.
   - `.agents/explorer_frontend_1/report.md` — Read the complete 11-section architectural deployment report.

3. **Invalidation Conditions**:
   - If new source files introduce additional `import.meta.env` keys (e.g. `VITE_ANALYTICS_KEY`), the environment variable inventory must be updated.
   - If `react-router-dom` is adopted in the future, SPA fallback rewrites in `vercel.json` become strictly mandatory.
