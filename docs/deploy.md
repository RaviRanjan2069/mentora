# Free public demo (Render + MongoDB Atlas)

A public Mentora demo for ₹0: one Render free web service (FastAPI serving the plain HTML/CSS/JavaScript
app at `/app`) and a MongoDB Atlas free M0 cluster. No domain, no card, no API key.

> The demo runs on a **synthetic course** with no simulated students. Nothing in it has been
> validated with real learners. Do not put real student data into the public demo.

## What runs where

| Part | Where | Free-tier terms (checked 2026-10-19) |
|---|---|---|
| API + web app | Render free web service, Docker | 512 MB RAM, 0.1 vCPU, 750 instance-hours/month, spins down after 15 min idle (~1 min cold start), ephemeral disk, no card needed |
| Database | MongoDB Atlas M0, AWS Singapore (`ap-southeast-1`) | 512 MB storage, shared CPU/RAM, 100 operations/s, 500 connections, 10 GB in + 10 GB out per 7 days, **no backups**, paused after 30 days with zero connections (resume from the Atlas UI), free forever, no card |

Why Render: Hugging Face Docker Spaces need a paid plan, Railway is a trial credit, Fly.io
has no free tier for new accounts. Put Atlas in the same region as Render (Singapore) so
each database round trip is a few milliseconds; a tutor turn makes about 25.

### Demo configuration (Render → mentora → Environment)

| Setting | Value | Why |
|---|---|---|
| `MENTORA_DATABASE_URL` | secret | Atlas connection string (below). |
| `MENTORA_LLM__BACKEND` | `offline` (or `local`, see the end) | Template replies, no API key. The UI shows a "Demo mode" notice. |
| `MENTORA_RAG__EMBEDDER` / `RERANKER` / `GROUNDING_JUDGE` | `hashing` / `lexical` / `lexical` | No model downloads; torch is never imported, so the API fits in 512 MB. **The DB must be seeded with the same embedder.** |
| `MENTORA_RAG__ANSWER_MODE` | `course_only` | Offline templates can only answer from the notes; `open` needs a real model. |
| `MENTORA_DEV_LOGIN` | `true` | No Moodle: sign in from the login page. |
| `MENTORA_DEV_TEACHER_CODE` | secret | Only for the developer sign-in form (off in production). Account sign-up needs no code: every teacher gets a random 10-digit class code. |
| `MENTORA_COOKIE_HTTPS_ONLY` | `true` | Render serves HTTPS. |
| `MENTORA_SESSION_SECRET`, `MENTORA_PSEUDONYM_SALT` | long random | Keep the salt fixed once learners exist. |
| `MENTORA_DEV_LOGIN` | `false` once accounts are used | Everyone signs up / in with an account (D41). |
| `MENTORA_BREVO_API_KEY`, `MENTORA_MAIL_FROM`, `MENTORA_MAIL_FROM_NAME` | secret / your verified sender / `Mentora` | Verification and password-reset emails. |
| `MENTORA_PUBLIC_BASE_URL` | `https://<service>.onrender.com` | Links in emails point here. |

## First deployment

### 1. Atlas cluster (Atlas CLI, browser sign-in)

```bash
atlas auth login --authType UserAccount --output json      # sign in in the browser, enter the code
atlas clusters create mentora --provider AWS --region AP_SOUTHEAST_1 --tier M0 --projectId <project>
atlas clusters watch mentora --projectId <project>
atlas dbusers create --username mentora_app --password <long random> --role readWrite@mentora --projectId <project>
atlas accessLists create 0.0.0.0/0 --type cidrBlock --projectId <project>   # Render free has no fixed IPs
atlas clusters describe mentora --projectId <project>      # standardSrv: mongodb+srv://mentora.<id>.mongodb.net
```

The one-time sign-in code expires after 3 minutes: be signed in on
<https://account.mongodb.com/account/connect> before generating it. The Atlas UI works too
(*Create* → *M0 Free* → AWS Singapore; *Database Access*; *Network Access*). The app user
can only read and write the `mentora` database.

`MENTORA_DATABASE_URL` is
`mongodb+srv://mentora_app:<password>@mentora.<id>.mongodb.net/mentora?retryWrites=true&w=majority&appName=mentora`.
Keep it secret: it is the password to every learner's data.

### 2. Indexes and seed (once, from your computer)

PowerShell, from the repo root with the venv active:

```powershell
$env:MENTORA_DATABASE_URL = "mongodb+srv://mentora_app:<password>@mentora.<id>.mongodb.net/mentora?retryWrites=true&w=majority"
$env:MENTORA_RAG__EMBEDDER = "hashing"      # must match the deployed setting
$env:MENTORA_LLM__BACKEND = "offline"
python scripts/init_db.py                    # indexes + schema version (the API also does this)
python scripts/seed_demo.py                  # course, quiz items, course notes, rule policy (~12 s)
Remove-Item Env:MENTORA_DATABASE_URL, Env:MENTORA_RAG__EMBEDDER, Env:MENTORA_LLM__BACKEND
```

Re-running `seed_demo.py` is safe (course, items, passages and the rule policy are
upserted). Do not use `--with-history` on the public demo: it adds simulated students
(`lrn_sim_*`). To remove simulated students with everything that belongs to them, use the
app's store, because deleting documents in Compass or `mongosh` does **not** cascade:

```python
from mentora.config import get_settings
from mentora.db import connect
from mentora.db import models as m

with connect(get_settings().database_url).begin() as db:
    print(db.delete_many(m.Learner, {"id": {"$regex": "^lrn_sim_"}}))
```

`pytest -m mongo` creates and drops a throwaway database, which the Atlas app user may not
do: run it against a local MongoDB or in CI.

### 3. Render service

1. Sign up at <https://render.com> with GitHub (Hobby workspace, no card).
2. *New* → *Web Service* → *Public Git repository* `https://github.com/RaviRanjan2069/mentora`,
   runtime Docker, instance type *Free*, region Singapore, health check path `/health`.
   (Or *New* → *Blueprint*: `render.yaml` has the same settings.)
3. Set the environment variables above. The first Docker build takes about 10 minutes.
   The API creates the indexes on start and listens on Render's `$PORT`.
4. Open `https://<service>.onrender.com/health` (`"schema_version": "v1-mongo"`,
   `"database": "ok"`), then `/app/`.

### 4. Verify the live site

```bash
python scripts/smoke_deploy.py https://<service>.onrender.com --teacher-code <code>
```

It checks health, the web app and its assets, role separation, retrieval, a tutor session,
a quiz answer with confidence, a distress escalation answered by the teacher, and the
teacher console. It writes one demo learner and one escalation; that is expected.

## Accounts and email (Brevo, free)

1. Sign up at <https://www.brevo.com> (free: 300 emails a day, no card; emails carry Brevo's logo).
2. *Senders, domains & dedicated IPs* → *Senders* → add the address mails come from (e.g. your
   Gmail) and confirm it from the email Brevo sends.
3. *SMTP & API* → *API keys* → generate a key.
4. On Render set `MENTORA_BREVO_API_KEY`, `MENTORA_MAIL_FROM` (the confirmed sender),
   `MENTORA_PUBLIC_BASE_URL` and `MENTORA_DEV_LOGIN=false`, then deploy.
5. Create an account on the site: the confirmation email arrives within a minute (check spam the
   first time). Teachers sign up with the teacher code; students join them from *My Teachers*.

Accounts hold personal data (email, name, gender, photo) on Atlas M0, which has no backups. Anyone
can delete their own account and data from *Profile*.

## Updating

A service created from a public repository URL is not connected to GitHub, so pushes do not
deploy by themselves: use *Manual Deploy* → *Deploy latest commit* (or connect Render's
GitHub app in the service settings for automatic deploys). New indexes are created on
start; changes that need existing documents rewritten need a one-off script. Atlas M0 has
no backups: before such a change, export what matters with `mongodump` or Compass.

## Limits and risks

- **Cold starts**: Render's free service sleeps after 15 idle minutes (about a minute to
  wake). `.github/workflows/keepalive.yml` pings `/health` every 10 minutes so it stays
  awake (750 free hours a month cover one service all month). GitHub can start scheduled
  runs late, and pauses schedules after 60 days without repository activity.
- **Ephemeral disk**: anything written under the container (`models/`, trained policy
  files, `llm_cache/`) is lost on every restart or redeploy. Learner data, sessions,
  escalations, memory and uploaded course material are in Atlas and survive.
- **No backups and no transactions**: Atlas M0 is not backed up, and a crash in the middle
  of a write can leave it partial (docs/decisions.md D39).
- **Approving a learned policy** stores its model file on that ephemeral disk. After the
  next restart the file is gone and the tutor cannot load its policy. In the demo, approve
  only the rule policy, or retire the learned one (see below). Policy training in the
  console imports PyTorch and may run out of memory or take very long on 0.1 vCPU; run
  `python scripts/train_policy.py` locally against Atlas instead.
- **Offline replies** are templates that quote course passages. They are not an LLM, the
  model-free retrieval is crude, and off-topic questions are not always recognised.
- `/api/rag/search` and `/docs` are public (they show only the synthetic course notes and
  the API schema).
- **Atlas M0 limits**: 100 operations per second (about 4 tutor turns per second across all
  users), 512 MB, 10 GB transfer per direction per week; the cluster pauses after 30 days
  without any connection. Render: if free bandwidth or build minutes run out, the service is
  suspended for the month. Nothing is charged without a card on file.
- **Network access** is open to all IPs (Render has no fixed IPs on the free plan); access
  depends on the strong, database-scoped password over TLS.
- Anyone with the URL can create demo learner accounts.

### Recovering from a lost policy file

In Compass or `mongosh`, database `mentora`:

```js
db.policies.updateMany({ status: "active", type: { $ne: "rule" } }, { $set: { status: "retired" } })
db.policies.updateOne({ _id: "rule-v1" }, { $set: { status: "active" } })
```

Then restart the service (Render → *Manual Deploy* → *Restart*).

## Optional: real LLM replies

**Claude (paid)**: set `ANTHROPIC_API_KEY` as a Render secret and
`MENTORA_LLM__BACKEND=hosted`, `MENTORA_RAG__ANSWER_MODE=open`. This leaves the ₹0 plan.

**Ollama on your own computer (free)**: the Render instance is too small to run a model,
so the deployed app calls your computer through a tunnel. Tutor replies only work while
your computer, Ollama, the gateway and the tunnel are all running; otherwise tutor turns
fail after the timeout (switch back to `offline` when you stop).

1. Sign up at <https://ngrok.com> (free, no card; 1 permanent dev domain, 20k requests and
   1 GB per month) and save the authtoken:
   `& "$env:LOCALAPPDATA\ngrok\ngrok.exe" config add-authtoken <token>` (agent from
   <https://ngrok.com/download>, unzipped to `%LOCALAPPDATA%\ngrok`).
2. Put a long random token and your domain in the git-ignored `.env`:
   `OLLAMA_GATEWAY_TOKEN=<token>` and `NGROK_DOMAIN=<name>.ngrok-free.dev`.
3. Run `powershell -ExecutionPolicy Bypass -File scripts\install_tutor_autostart.ps1
   -NeverSleepOnAC` once: a scheduled task runs `scripts\start_tutor_tunnel.ps1` hidden at
   sign-in and every 5 minutes, restarting whatever stopped, and the computer no longer
   sleeps on its own while plugged in (`-Remove` uninstalls the task). The script starts
   Ollama if needed, the token gateway on 127.0.0.1:11435 (`scripts/ollama_gateway.py`; never tunnel Ollama's port
   11434 itself: its API can pull and delete models) and ngrok on the permanent domain,
   then checks the whole path. The URL never changes, so Render is set once.
   (A Cloudflare quick tunnel, `cloudflared tunnel --url http://127.0.0.1:11435`, needs no
   account but gets a new URL on every restart.)
4. On Render set: `MENTORA_LLM__BACKEND=local`, `MENTORA_LLM__LOCAL_MODEL=llama3.2:3b`,
   `MENTORA_LOCAL_LLM_BASE_URL=https://<name>.ngrok-free.dev/v1`,
   `MENTORA_LOCAL_LLM_API_KEY=<token>`, `MENTORA_LLM__TIMEOUT_S=180`,
   `MENTORA_RAG__ANSWER_MODE=open`, `MENTORA_RAG__ANSWER_REGENERATIONS=0`, and
   `MENTORA_LLM__LOCAL_FALLBACK=offline`: while the computer is off, the tutor answers from
   the course notes (shown as Demo mode) instead of failing, and goes back to the model
   within a minute of it being reachable again. Teacher console → System status shows
   whether the model is reachable.
5. To stop: set `MENTORA_LLM__BACKEND=offline` and `MENTORA_RAG__ANSWER_MODE=course_only`.
