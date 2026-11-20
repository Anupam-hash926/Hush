# Hush

Hush is a quorum-gated secret management workspace built with **FastAPI**, **Neo4j**, and **Redis**, paired with a vanilla-JS single-page application (SPA) frontend. Secrets are encrypted at rest with AES-256-GCM, and requesters must obtain live quorum approvals from authorized project approvers before claiming a short-lived, view-bounded access token.

## Architecture

* **Backend API (`app/`)**: FastAPI application providing JWT authentication, password hashing, project and role management, encrypted secret storage, time-bounded quorum evaluation, claim-window enforcement, immediate access revocation, and audit logging.

* **Graph Database (`Neo4j`)**: Models relational and graph-based authorization state across `User`, `Project`, `Secret`, `AccessRequest`, and `AuditEvent` nodes (`OWNS`, `HAS_ACCESS` with `viewer` or `editor` roles, `REVIEWER_OF`, `CONTAINS`, `MADE`, `FOR`, `PERFORMED`, and `ABOUT`).

* **Ephemeral & Atomic State (`Redis`)**: Tracks pending request flags (`request:{request_id}:pending`), live approval timestamps in Sorted Sets (`approvals:{request_id}` with per-approval expiry scores), claim-window locks (`approved_window:{request_id}` bounded by the shortest remaining validity among live quorum approvals), one-time access tokens (`vault_token:{token}`), reverse-lookup keys (`active_token:{secret_id}:{user}`), and atomic view counters (`views:{token}`).

* **Frontend (`Frontend/`)**: Vanilla-JS SPA served through Vite (proxying `/api` to `:8000`) featuring a metadata-only vault, per-secret request/claim/view lifecycle, an approvals inbox with configurable approval validity windows, and owner-only revocation and audit log views.

## Setup & Running

### 1. Configure Environment Variables

Copy `.env.example` to `.env` at the repository root and set strong values for your database credentials and secret keys:

```
cp .env.example .env

```

### 2. Start Neo4j and Redis

Start the backing services with Docker Compose:

```
docker compose up -d

```

### 3. Run the FastAPI Backend

Create and activate a virtual environment, install dependencies, and start Uvicorn:

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

```

### 4. Run the Frontend SPA

In a second terminal, install frontend packages and launch the Vite dev server:

```
cd Frontend
npm install
npm run dev

```

### 5. Run the Test Suite

With Neo4j and Redis running, execute `pytest` from the repository root:

```
PYTHONPATH=. pytest -v

```

## API Endpoints

| Method | Path | Description | 
| ----- | ----- | ----- | 
| `POST` | `/register` | Register a new user account | 
| `POST` | `/login` | Authenticate credentials and issue a JWT bearer token | 
| `GET` | `/me` | Return the currently authenticated user | 
| `POST` | `/projects` | Create a project with the caller as owner | 
| `GET` | `/projects` | List projects owned by or shared with the caller | 
| `POST` | `/projects/{project_id}/share` | Grant `viewer` or `editor` access to a user (owner only) | 
| `POST` | `/projects/{project_id}/reviewers` | Assign a `REVIEWER_OF` relationship on a project (owner only) | 
| `POST` | `/projects/{project_id}/secrets` | Encrypt and store a secret with quorum and view limits (owner or `editor`) | 
| `GET` | `/projects/{project_id}/secrets` | List non-sensitive secret metadata (no plaintext) | 
| `GET` | `/projects/{project_id}/secrets/{secret_id}/approvers` | Discover eligible approvers for a secret (excludes caller) | 
| `GET` | `/approvals/inbox` | List pending requests across projects where the caller can approve | 
| `POST` | `/projects/{project_id}/secrets/{secret_id}/request` | Create or return an active (`pending` or `approved`) access request | 
| `GET` | `/projects/{project_id}/secrets/{secret_id}/request-status` | Fetch request status and live approval count | 
| `POST` | `/projects/{project_id}/secrets/{secret_id}/approve` | Record a time-bounded approval; flip to `approved` when quorum is met | 
| `POST` | `/projects/{project_id}/secrets/{secret_id}/reject` | Reject a pending request and clear Redis approval state | 
| `POST` | `/projects/{project_id}/secrets/{secret_id}/claim` | Claim a one-time access token if within the active claim window | 
| `POST` | `/secrets/access/{access_token}` | Decrypt a secret and atomically increment/enforce its view counter | 
| `POST` | `/projects/{project_id}/secrets/{secret_id}/revoke` | Revoke active requests and immediately invalidate active tokens (owner only) | 
| `GET` | `/projects/{project_id}/secrets/{secret_id}/audit` | Retrieve audit log events for a secret (owner only) | 

## Request State Machine

```
(none) ──► pending ──► approved ──► claimed ──► consumed (views_remaining == 0)
               │           │           │
               │           ▼           ▼
               │        expired     revoked
               ▼
           rejected / revoked

```

* **Approval Validity & Claim Window**: Approvers specify `approval_validity_seconds` when approving (defaulting to `86400` seconds / 24 hours). Once quorum is reached, the claim window (`approved_window:{request_id}`) is bounded by the shortest remaining validity among the live approvals that completed quorum. Attempting to claim after that window expires returns `410 Gone` and marks the request as `expired`.