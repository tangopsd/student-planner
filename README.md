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

Put the Gemini key in `backend/.env` (that file is gitignored):

```bash
GEMINI_API_KEY=your_key_here
```

Replace `your_key_here`, save, then restart the API. The process reads `.env` only at startup. In the terminal where the API is running, press Ctrl+C, then:

```bash
cd backend
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8741
```

Leave the frontend running. `GEMINI_MODEL` is optional and defaults to `gemini-3.6-flash`. If that model is busy, the desk tries another model and shows a short message only when all of them fail. A key already exported in the shell wins over the file. The placeholder is ignored, so planning stays local until a real key is saved.

`POST /api/plan/gemini` schedules the deadlines already in `data/state.json`. With a key, Gemini calls the planner tools and the validator retries once, sending the validator text back on that retry. Without a key, the desk still builds that week locally from the same deadlines, and a typed move updates the week that is already there. If the retry still fails, the page shows one short sentence. **Plan this week** shows the blocks in the day columns. It does not regenerate the deadlines.

The same planner answers typed and spoken requests at `POST /api/voice`. Type a change and press **Send**, or hold **Hold to talk**. The transcript and the reply stay on the page. The mic toggle is off until you turn it on; only then does the desk speak the reply. Audio transcription needs `GEMINI_API_KEY`. Typed requests still plan without it. A successful turn replaces the blocks in the weekly list.

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
| `POST` | `/api/voice` | JSON `{"text": "...", "week_start": "YYYY-MM-DD"}`, or multipart with `text` or an `audio` file. Returns the transcript, reply, and updated plan. |

Gemini tools are `list_items`, `add_item`, `move_item`, `create_blocks`, `move_block`, `delete_block`, `get_week_plan`, `set_constraint`, `mark_progress`, and `undo_last_change`. The validator rejects overlapping blocks, blocks outside waking hours, study time over the daily capacity, and any move of a locked deadline. Study and personal time count toward capacity. Fixed and buffer blocks do not. A deadline stored at local midnight can be studied until sleep that day.
