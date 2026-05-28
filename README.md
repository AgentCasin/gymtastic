# Gymtastic

A lightweight smart gym management system built with **FastHTML**, **MonsterUI**, and **SQLModel**.
It handles member bookings, trainer schedules, admin oversight, and 
simulated smart lockers with real-time congestion tracking.
## Quick Start

We have a test feature  (Start up test) that works as follow:

**cd into the installation folder**
**RUN**
```
uv run test_app.py
```
Then you can proceed to the main program
```
uv run main.py
```

We use **uv** for fast dependency management and execution.
**Install dependencies:**

```
uv sync
```
**Run the app:**

```
uv run python main.py
```

The server starts at `http://127.0.0.1:8000`. The database initializes automatically.
## How It Works
**Members:** Book trainer sessions, check gym congestion, and unlock digital lockers.
**Trainers:** View their schedule and profile details.
**Admins:** Manage users and monitor live occupancy stats.
**Tech:** Uses HTMX for dynamic updates and SQLModel for the database.

*Note: Password hashing is currently SHA256 (demo only). Replace with bcrypt for production.*


