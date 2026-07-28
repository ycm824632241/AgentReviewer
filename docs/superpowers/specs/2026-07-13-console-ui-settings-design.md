# AgentReviewer Console UI And Settings Design

## Goal

Update the React demo to a clean console style inspired by the provided reference: white background, thin borders, generous spacing, black primary actions, and simple top navigation.

## Navigation

Use three top-level navigation items:

- 审稿台: upload, progress, editor decision, reviewer reports, and Rebuttal remain in one workflow.
- 历史记录: history list and thread opening.
- 设置: model connection settings.

Rebuttal is not a separate route because it is a continuation of the review workflow after results are available.

## Settings

The first settings version exposes only model connection fields:

- 审稿 LLM: `MIMO_BASE_URL`, `MIMO_API_KEY`, `MIMO_MODEL_DEBATER`
- Embedding 模型: `GITEE_BASE_URL`, `GITEE_API_KEY`, `GITEE_EMBED_MODEL`

Settings are read from and written to `20-multi-agent-debate/.env`. API keys are returned to the browser as masked values and can be overwritten by entering a new value.

## Backend

Add FastAPI endpoints:

- `GET /api/settings`: returns current model URLs, model names, and masked key status.
- `POST /api/settings`: updates the supported environment keys in the `.env` file.

Running review jobs use the configuration loaded when their model clients are created. New review jobs use updated settings.

## Frontend

Keep the existing single React app and add client-side navigation state. No React Router is needed.

Use console-style visual treatment:

- top nav with active underline
- large page heading
- rounded white panels with thin gray borders
- black primary buttons and white secondary buttons
- segmented controls for reviewer pages

## Verification

Add tests for:

- settings API reads and writes the supported keys
- frontend contains the three navigation items and settings form fields
- existing result rendering still works

Run the relevant pytest suite and `npm run build`.
