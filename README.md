# Desk

A student desk for deadlines. Paste a Canvas (or any iCal) feed, upload a `.ics` file, or type a deadline by hand. The page groups them by the week they fall in. Exams and midterms are locked.

There is no login and no database. Profile, deadlines, and plan versions live in one file, `data/state.json`, so a restart keeps them.

## Run it

Backend, from the repo root:

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8741
```

Frontend, in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://127.0.0.1:8742](http://127.0.0.1:8742). The dev server proxies `/api` to port 8741.

After the venv and `npm install`, `./scripts/dev.sh` starts both.

If you have no feed yet, use **Load sample calendar** or **Add by hand**.

## Weekly plan

Set `GEMINI_API_KEY` in the environment before starting the backend. `GEMINI_MODEL` defaults to `gemini-2.5-flash`.

`POST /api/plan/gemini` sends the deadlines and profile already in `data/state.json` to Gemini, runs the tool calls, and checks the week. If the plan is invalid it retries once. The page shows that week under **Weekly plan**. **Plan this week** asks for blocks around the deadlines already on the desk. It does not regenerate them.

Without `GEMINI_API_KEY` the endpoint returns 400 and leaves the file unchanged.

## Tests

```bash
cd backend
.venv/bin/pytest
```

`python backend/ical_parser.py` checks the two built-in iCal examples.

## What is stored

`data/state.json`:

- **Profile** — waking hours, fixed weekly commitments, preferred study windows, daily study capacity in hours.
- **Items** — id, title, course, type (`assignment`, `quiz`, `exam`, `event`, `personal`), due or start time, source (`canvas`, `voice`, `manual`), estimated effort in hours, locked flag, status (`open` or `done`). Feed text is kept in `description`.
- **Plans** — week start (Monday), blocks, version, previous version, and a change log. A block has an id, a linked item, start, end, kind, status, and a reason.

Times are America/Los_Angeles. Weeks start on Monday.

Importing the same feed again refreshes title, course, type, time, and description, and leaves effort and status alone. An exam stays locked.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/weeks` | Deadlines grouped by week |
| `POST` | `/api/calendar` | JSON `{"url": "..."}` or a multipart `.ics` field named `file` |
| `POST` | `/api/calendar/sample` | Import `data/sample-calendar.ics` |
| `POST` | `/api/items` | Typed deadline |
| `PATCH` / `DELETE` | `/api/items/{id}` | Update or remove one |
| `GET` / `PUT` | `/api/profile` | Read or replace the student profile |
| `GET` | `/api/classify?title=` | Keyword type (`matched` is false when nothing hit) |
| `GET` / `POST` | `/api/plans` | List plan versions, or append the next version for a Monday |
| `POST` | `/api/plan/gemini` | JSON `{"request": "Plan this week", "week_start": "YYYY-MM-DD"}`. `week_start` is optional. |

Gemini tools are `list_items`, `add_item`, `move_item`, `create_blocks`, `move_block`, `delete_block`, `get_week_plan`, `set_constraint`, `mark_progress`, and `undo_last_change`. The validator rejects overlapping blocks, blocks outside waking hours, study time over the daily capacity, and any move of a locked deadline. Study and personal time count toward capacity. Fixed and buffer blocks do not. A deadline stored at local midnight can be studied until sleep that day.
