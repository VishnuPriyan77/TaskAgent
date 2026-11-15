# TaskPilot — Project B

TaskPilot is a task manager controlled through a chat assistant. The assistant uses LLM function calling to list, create, update, and delete the signed-in user's tasks, including multiple actions in one request. The task list refreshes after each response, including errors.

## Live demo

- Frontend: https://taskpilot-frontend-bvishnupriyan2006-9902s-projects.vercel.app
- Backend API documentation: https://taskpilot-backend-bvishnupriyan2006-9902s-projects.vercel.app/docs
- Admin: admin@taskpilot.demo / au91rrejimVOhpW0
- User: user@taskpilot.demo / VaI21Y3Q_lRk2qy8

These accounts are public demo accounts. Their tasks may be changed by other reviewers; do not store private information in them. Free-tier limits can affect availability.

## Stack and design

- FastAPI and SQLAlchemy implement the API and persistent storage; Supabase PostgreSQL persists deployed data in a separate schema with row-level security. SQLite is only a local convenience.
- React and Vite provide the frontend.
- Gemini’s OpenAI-compatible tool-calling API runs the agent. The model is configurable via `GEMINI_MODEL` (default `gemini-3.5-flash-lite`).
- Passwords are Argon2-hashed; signed JWTs expire after 12 hours. Every signup receives the user role. A trusted operator promotes an existing account using a server-side script; there is no public admin promotion endpoint.
- The backend selects tasks using the authenticated user's ID on every tool invocation, even for admins. The admin overview is a separate, backend-protected read-only endpoint. No user-provided owner ID is trusted.
- The agent can make several tool calls across multiple rounds. Results are passed back to the model and displayed as an expandable tool trace. The application commits each action separately; if a later step fails, earlier actions remain saved and the UI warns users to inspect the list.

## Local setup

Prerequisites: Python 3.10+, Node.js 18+, and a Gemini API key. The AI API may incur charges or limits depending on the provider account; check its current free-tier terms.

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export JWT_SECRET="replace-with-a-long-random-secret-at-least-32-characters"
export GEMINI_API_KEY="your-key"
# Optional local default: sqlite:///./taskpilot.db
# export DATABASE_URL="postgresql://user:password@host/database?sslmode=require"
uvicorn app.main:app --reload
```

In a separate terminal:

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. API docs are at `http://localhost:8000/docs`. Sign up for two accounts. To promote one account, run from `backend` with the same `DATABASE_URL` and `JWT_SECRET` environment variables as the server:

```sh
python seed_admin.py admin@example.com
```

Log out and back in. Never commit real credentials or environment files. Use `.env.example` as a list of environment variables; the application reads environment variables directly, so export them or configure them in your host.

## Deployment

1. Create a hosted PostgreSQL database and obtain its connection URL. Set `DATABASE_URL`, a unique random `JWT_SECRET` of at least 32 characters, `GEMINI_API_KEY`, and `CORS_ORIGINS` (the exact frontend origin) on the backend host. Optionally set `GEMINI_MODEL`.
2. Deploy the `backend` directory as a Python web service with build command `pip install -r requirements.txt` and start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Deploy `frontend` as a Vite static site with build command `npm install && npm run build`, output directory `dist`, and `VITE_API_URL` set to the backend origin without a trailing slash. Configure the backend CORS origin to match the deployed frontend.
4. Create demo accounts and promote the admin using trusted server-side database access and `seed_admin.py`, then record demo credentials and URLs in this README. Verify both roles in a private browser window and check `/docs`.

## Extras and limitations

Extra features: task due dates and completion status, visible tool calls, and a cross-user admin overview. Deleting is prompted by an explicit request but there is no separate confirmation dialog. Chat history is kept only in the current browser session, not persisted or sent back to the model; each message should therefore be self-contained. Relative dates use UTC. Signup/login are a minimal demonstration and lack rate limiting, account recovery, email verification, and production-grade session revocation. Schema creation is automatic and migrations are not included. The app requires a working Gemini key; error messages flag that changes may already have occurred if the provider fails after a tool call. Local SQLite data should not be used for deployed storage.

## Tests

```sh
cd backend
pip install pytest
PYTHONPATH=. pytest
```

The tests cover backend role enforcement, user isolation, and a mocked multi-step tool-calling exchange. The deployed provider was also tested with a real create request and a multi-step update-and-create request.
