# Quill

An AI productivity planner for college students. Paste a Canvas (or any iCal) feed, upload a `.ics` file, or type a deadline by hand. Quill turns your deadlines into a weekly study plan that adapts when life changes.

There is no login and no database. Profile, deadlines, and plan versions live in one file, `data/state.json`, so a restart keeps them.

## Run it

Backend, from the repo root:

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8741
