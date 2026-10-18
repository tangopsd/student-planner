# Quill

An AI productivity planner for college students. Paste a Canvas (or any iCal) feed, upload a `.ics` file, or type a deadline by hand, and Quill turns your deadlines into a weekly study plan that adapts when life changes.

There is no login and no database. Your profile, deadlines, and plan versions live in a single file, `data/state.json`, so a restart keeps everything.

## Features

- **Flexible import**: Canvas/iCal URL, `.ics` upload, or manual entry.
- **Month calendar home**: deadlines and planned blocks land on their days. The grid is shown even when nothing is saved yet.
- **Weekly plan**: type a change in plain language and Gemini updates your week.
- **Recap card**: blocks finished vs. planned, a streak, and your heaviest day. Download or copy it as a picture.
- **Study page**: countdown timer, stopwatch, a checklist synced with your plan, and embedded Spotify playlists.

## Quick start

### 1. Backend

From the repo root:

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8741
```

### 2. Frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:8742>. The dev server proxies `/api` to port 8741.

### Shortcut

After creating the venv and running `npm install`, `./scripts/dev.sh` starts both servers.

### No feed yet?

Use **Load sample calendar** or **Add by hand**.

## Enabling the weekly plan (Gemini)

Put your key in `backend/.env` (this file is gitignored):

```bash
GEMINI_API_KEY=your_key_here
```

Replace `your_key_here`, save, then **restart the API**. The process only reads `.env` at startup. In the terminal where the API is running, press `Ctrl+C` and
