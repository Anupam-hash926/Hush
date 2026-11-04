# Hush frontend

A responsive, dependency-light frontend for the Hush FastAPI backend. The interface covers account registration and login, project creation, project sharing, secret creation and on-demand reveal, access requests, and manual approval or rejection of a known request.

The public home page links into sign-in and registration. Signed-in users can open profile settings from the sidebar or top bar, choose a bright or dark theme (saved on the current device), and confirm before signing out.

## Run locally

1. Start the backend and its configured Neo4j and Redis services from the repository root.
2. From this folder, install the frontend dependency and start Vite:

   ```sh
   npm install
   npm run dev
   ```

   In PowerShell, if script execution blocks `npm`, use `npm.cmd install` and `npm.cmd run dev`.

3. Open the local URL printed by Vite (by default `http://localhost:5173`).

Vite forwards `/api` requests to `http://127.0.0.1:8000`, so the backend does not need CORS changes for local development. Set the backend host in [vite.config.js](./vite.config.js) if it runs elsewhere.

## Backend limitations reflected in the UI

- The API does not expose a pending-request inbox. To review a request, the project owner or editor needs the requester's email and secret ID.
- The API's reveal operation decrypts every secret in the selected project. Hush calls it only after the user explicitly chooses to reveal that project's secrets.
- The API response does not include project member lists or per-secret view counts, so the interface does not invent or display those values.
- Production hosting must route `/api` to the FastAPI service, or provide an equivalent same-origin reverse proxy.
