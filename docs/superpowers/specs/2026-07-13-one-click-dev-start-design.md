# One-Click Dev Start Design

## Goal

Add a Windows PowerShell script that starts the React + Vite frontend and FastAPI backend together for local development.

## Design

Create `start_dev.ps1` at the project root. The script resolves the repository root from its own location, checks Python and Node.js availability, optionally installs Python and npm dependencies with `-Install`, then starts FastAPI and Vite in two separate PowerShell windows.

The frontend remains the primary user entry point at `http://localhost:5173`. The backend continues to run on `http://127.0.0.1:8000`, and Vite proxies `/api` calls to FastAPI.

## Parameters

- `BackendHost`: defaults to `127.0.0.1`.
- `BackendPort`: defaults to `8000`.
- `FrontendHost`: defaults to `localhost`.
- `FrontendPort`: defaults to `5173`.
- `Install`: installs Python and frontend dependencies before startup.
- `NoOpen`: skips opening the browser.
- `NoReload`: starts FastAPI without reload.

## Error Handling

The script fails early when Python or npm is unavailable. It warns when `20-multi-agent-debate\.env` is missing because the UI can launch without it, but real review jobs need model API settings.

## Testing

Run syntax parsing for `start_dev.ps1`, run `.\start_dev.ps1 -CheckOnly` if available behavior is added, and verify the existing backend/frontend checks still pass:

- `.\start_web.ps1 -CheckOnly`
- `npm run build` in `frontend`
