# Quill ✒️

**An AI study planner for college students.** Quill pulls in your Canvas and calendar deadlines, then uses Gemini to turn them into a realistic weekly study plan that adapts as your semester changes.

Clone it, add an API key, and run it on your machine.

<!-- TODO: add a screenshot or GIF of the weekly plan view here -->
<!-- ![Quill screenshot](docs/screenshot.png) -->

---

## Table of Contents

- [Why Quill?](#why-quill)
- [Features](#features)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Data & Privacy](#data--privacy)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## Why Quill?

Most planners make you do the hard part yourself: reading every syllabus, estimating how long each assignment will take, and deciding what to work on first. Deadlines live in Canvas, classes live in a calendar, and the actual plan lives in your head.

Quill closes that gap. It collects deadlines from the places they already live and produces a concrete, day-by-day plan you can follow, then re-plans when things slip or new work appears.

## Features

- **Canvas and iCal import.** Bring in assignments and due dates from Canvas or any standard `.ics` / iCal feed.
- **AI-generated weekly plan.** Gemini breaks deadlines into study blocks and spreads them across the week based on due dates and workload.
- **Adaptive re-planning.** Missed a block or got a new assignment? Regenerate and the plan adjusts around what's left.
- **Simple local storage.** Your tasks and plan are saved to a single JSON file (`data/state.json`), so there's nothing extra to install or configure.
- **Runs on your machine.** The only outbound call is to the Gemini API for planning.

## How It Works

```
 Canvas / iCal feed
        │
        ▼
 ┌────────────────┐     deadlines      ┌──────────────────┐
 │ FastAPI backend│ ─────────────────► │   Gemini API     │
 │  (port 8741)   │ ◄───────────────── │ (plan generation)│
 └───────┬────────┘   weekly study plan└──────────────────┘
         │
         │ reads / writes
         ▼
   data/state.json
         ▲
         │ REST
 ┌───────┴────────┐
 │ JS frontend    │
 │ (dev: 8742)    │
 └────────────────┘
```

1. **Import**: you upload an iCal file or connect Canvas; the backend parses events into a normalized list of tasks with due dates.
2. **Plan**: the backend sends your tasks, availability, and existing plan to Gemini and asks for a structured weekly schedule.
3. **Store**: the result is written to `data/state.json`.
4. **Display and adapt**: the frontend renders the plan; marking progress or adding work and re-planning produces an updated schedule.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Frontend | JavaScript (Vite dev server) |
| AI planning | Google Gemini API |
| Storage | Local JSON file (`data/state.json`) |
| Integrations | Canvas deadlines, iCal (`.ics`) |

## Getting Started

### Prerequisites

- **Python** 3.10 or newer
- **Node.js** 18 or newer, with npm
- A **Gemini API key** from [Google AI Studio](https://aistudio.google.com/)

### 1. Clone the repository

```bash
git clone https://github.com/tangopsd/student-planner.git
cd student-planner
```

### 2. Set up the backend

```bash
# from the backend directory (adjust the path to match the repo layout)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Add your API key

Create a `.env` file (or export the variable in your shell):

```bash
GEMINI_API_KEY=your_key_here
```

### 4. Start the backend

```bash
uvicorn main:app --reload --port 8741
```

The API will be available at `http://localhost:8741`, with interactive docs at `http://localhost:8741/docs` (FastAPI's built-in Swagger UI).

### 5. Start the frontend

In a second terminal:

```bash
cd frontend                      # adjust to match the repo layout
npm install
npm run dev -- --port 8742
```

Open **http://localhost:8742** in your browser.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | API key used for plan generation |

| Setting | Default | Notes |
|---|---|---|
| Backend port | `8741` | Change via the `--port` flag on `uvicorn` |
| Frontend dev port | `8742` | Change via the Vite `--port` flag |
| State file | `data/state.json` | Created on first run |

If you change the backend port, update the API base URL in the frontend config to match.

## Usage

1. **Import your deadlines.** Upload an `.ics` file (export one from Canvas, Google Calendar, or Apple Calendar) or connect your Canvas feed.
2. **Review the task list.** Check that due dates came through correctly and adjust anything that looks off.
3. **Generate your plan.** Quill produces a weekly study schedule built around your deadlines.
4. **Work the plan.** Mark blocks as done as you go.
5. **Re-plan when life happens.** Add new assignments or regenerate after falling behind, and the schedule reshuffles around the remaining work.

### Getting an iCal link from Canvas

In Canvas, open **Calendar → Calendar Feed** and copy the `.ics` URL. This feed contains your upcoming assignments and events across courses.

## Project Structure

> Update this tree to match the actual layout of the repo.

```
student-planner/
├── backend/              # FastAPI app: routes, import parsing, Gemini planning
├── frontend/             # JavaScript UI (Vite)
├── data/
│   └── state.json        # Local app state (created at runtime)
├── .env                  # Your API key (not committed)
└── README.md
```

## Data & Privacy

- All planner state is stored **locally** in `data/state.json`.
- When you generate a plan, your task titles, due dates, and schedule context are sent to the **Gemini API**. Don't include anything in your tasks you wouldn't want sent to that service.
- Never commit your `.env` file or API key. Make sure `.env` and `data/state.json` are listed in `.gitignore`.

## Roadmap

- [ ] **Next up:** ship Quill as a live, working website instead of running it locally
- [ ] Study-block reminders and notifications
- [ ] Drag-and-drop editing of the generated plan
- [ ] Per-course workload and difficulty weighting
- [ ] Export plan back to a calendar (`.ics`)


---

Built by [Tanisha Gopinath](https://github.com/tangopsd).
