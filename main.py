"""
Gymtastic: Smart Gym Management System MVP
FastHTML + MonsterUI + SQLModel
"""

import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional

from fasthtml.common import *
from monsterui.all import *
from sqlmodel import Session
from starlette.requests import Request
from starlette.responses import RedirectResponse

from components import (
    admin_user_table,
    alert,
    booking_card,
    congestion_widget,
    locker_unlock_button,
    login_form,
    member_dashboard_card,
    navbar,
    register_form,
    trainer_list,
)
from db import engine, init_db
from models import Booking, GymStatistics, Locker, Member, Trainer, User

# Initialize app
app, rt = fast_app(
    live=True,
    hdrs=(
        Theme.slate.headers(mode="light", icons="tabler", daisy=True),
    )
)

# Session middleware for auth
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

# Use environment secret if provided
SECRET_KEY = os.environ.get("SESSION_SECRET", "change_this_secret")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


# ============================================================================
# UTILITIES
# ============================================================================

def hash_password(password: str) -> str:
    """Hash password using SHA256 (for demo; use bcrypt in production)."""
    return hashlib.sha256(password.encode()).hexdigest()


def get_current_user(session_or_request) -> Optional[User]:
    """Retrieve current authenticated user from session or request."""
    # Accept either a raw session dict or a Starlette Request
    if isinstance(session_or_request, Request):
        sess = session_or_request.session
    else:
        sess = session_or_request or {}
    user_id = sess.get("user_id")
    if not user_id:
        return None
    with Session(engine) as db:
        return db.query(User).filter(User.id == user_id).first()


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@rt("/")
def home(request: Request):
    """Home page - redirect based on auth status."""
    user = get_current_user(request)
    if user:
        if user.role == "admin":
            return RedirectResponse(url="/admin-dashboard", status_code=303)
        elif user.role == "trainer":
            return RedirectResponse(url="/trainer-dashboard", status_code=303)
        else:
            return RedirectResponse(url="/member-dashboard", status_code=303)
    return Titled(
        "Gymtastic",
        navbar(),
        Div(
            Div(
                H1("Welcome to Gymtastic", cls="text-4xl font-bold mb-4"),
                P("Your Smart Gym Management System", cls="text-xl opacity-70 mb-8"),
                Div(
                    A("Login", href="/login", cls="btn btn-primary btn-lg"),
                    A("Register", href="/register", cls="btn btn-outline btn-lg"),
                    cls="space-x-4 flex gap-4"
                ),
                cls="card-body text-center"
            ),
            cls="card bg-base-100 shadow-xl max-w-2xl mx-auto mt-20"
        ),
    )


@rt("/login", methods=["get", "post"])
def login(request: Request, email: str = "", password: str = ""):
    """Login route - GET shows form, POST processes login."""
    if not email:
        return Titled("Login - Gymtastic", login_form())
    
    with Session(engine) as db:
        user = db.query(User).filter(User.email == email).first()
        
        if user and user.password_hash == hash_password(password):
            # Store user_id in session
            request.session["user_id"] = user.id
            if user.role == "admin":
                return RedirectResponse(url="/admin-dashboard", status_code=303)
            elif user.role == "trainer":
                return RedirectResponse(url="/trainer-dashboard", status_code=303)
            else:
                return RedirectResponse(url="/member-dashboard", status_code=303)
        
        return Titled(
            "Login - Gymtastic",
            alert("Invalid email or password", "error"),
            login_form()
        )


@rt("/register", methods=["get", "post"])
def register(request: Request, full_name: str = "", email: str = "", password: str = "", role: str = ""):
    """Register new user."""
    if not email:
        return Titled("Register - Gymtastic", register_form())
    
    with Session(engine) as db:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return Titled(
                "Register - Gymtastic",
                alert("Email already registered", "error"),
                register_form()
            )
        
        new_user = User(
            email=email,
            password_hash=hash_password(password),
            role=role or "member",
            full_name=full_name
        )
        db.add(new_user)
        db.flush()
        
        if role == "trainer":
            trainer = Trainer(user_id=new_user.id)
            db.add(trainer)
        elif role == "member":
            member = Member(user_id=new_user.id)
            db.add(member)
        
        db.commit()
        request.session["user_id"] = new_user.id
        
        return RedirectResponse(
            url="/member-dashboard" if role == "member" else "/trainer-dashboard",
            status_code=303
        )


@rt("/logout")
def logout(request: Request):
    """Logout user."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# ============================================================================
# MEMBER DASHBOARD
# ============================================================================

@rt("/member-dashboard")
def member_dashboard(request: Request):
    """Member dashboard with bookings, locker, and congestion."""
    user = get_current_user(request)
    if not user or user.role != "member":
        return RedirectResponse(url="/login", status_code=303)
    
    with Session(engine) as db:
        member = db.query(Member).filter(Member.user_id == user.id).first()
        bookings = db.query(Booking).filter(Booking.user_member_id == user.id).all()
        locker = db.query(Locker).filter(Locker.member_id == member.id).first() if member else None
        stats = db.query(GymStatistics).first()
    
    return Titled(
        "Member Dashboard - Gymtastic",
        navbar(user.full_name, user.role),
        Div(
            Div(
                member_dashboard_card(user.full_name, member.membership_type if member else "N/A"),
                cls="col-span-1"
            ),
            Div(
                H3("My Bookings", cls="text-lg font-bold mb-4"),
                Div(
                    *[
                        booking_card(
                            b.trainer.user.full_name,
                            b.scheduled_at.strftime("%b %d, %H:%M"),
                            b.status
                        )
                        for b in bookings
                    ],
                    cls="space-y-3" if bookings else ""
                ) if bookings else P("No bookings yet. Book a trainer!", cls="opacity-70"),
                cls="col-span-1"
            ),
            Div(
                locker_unlock_button(locker.id, locker.locker_number) if locker else P("No locker assigned"),
                cls="col-span-1"
            ),
            Div(
                congestion_widget(stats.current_occupancy if stats else 0, 100),
                cls="col-span-1"
            ),
            Div(
                H3("Book a Trainer", cls="text-lg font-bold mb-4"),
                Div(id="trainer-list"),
                cls="col-span-2",
                hx_get="/get-trainers",
                hx_trigger="load"
            ),
            cls="grid grid-cols-2 gap-6 p-6"
        ),
    )


# ============================================================================
# TRAINER DASHBOARD
# ============================================================================

@rt("/trainer-dashboard")
def trainer_dashboard(request: Request):
    """Trainer dashboard with bookings."""
    user = get_current_user(request)
    if not user or user.role != "trainer":
        return RedirectResponse(url="/login", status_code=303)
    
    with Session(engine) as db:
        trainer = db.query(Trainer).filter(Trainer.user_id == user.id).first()
        bookings = db.query(Booking).filter(Booking.trainer_id == trainer.id).all() if trainer else []
    
    return Titled(
        "Trainer Dashboard - Gymtastic",
        navbar(user.full_name, user.role),
        Div(
            Div(
                Div(
                    H3(user.full_name, cls="text-xl font-bold"),
                    P(f"Specialization: {trainer.specialization if trainer else 'N/A'}", 
                      cls="opacity-70"),
                    P(f"Rate: ${trainer.hourly_rate}/hr" if trainer else "",
                      cls="font-semibold text-success"),
                    cls="card-body"
                ),
                cls="card bg-base-100 shadow"
            ),
            Div(
                H3("Upcoming Sessions", cls="text-lg font-bold mb-4"),
                Div(
                    *[
                        booking_card(
                            b.member.user.full_name,
                            b.scheduled_at.strftime("%b %d, %H:%M"),
                            b.status
                        )
                        for b in bookings
                    ],
                    cls="space-y-3" if bookings else ""
                ) if bookings else P("No bookings scheduled", cls="opacity-70"),
                cls="col-span-1"
            ),
            cls="grid grid-cols-2 gap-6 p-6"
        ),
    )


# ============================================================================
# ADMIN DASHBOARD
# ============================================================================

@rt("/admin-dashboard")
def admin_dashboard(request: Request):
    """Admin dashboard with user management."""
    user = get_current_user(request)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    
    with Session(engine) as db:
        users = db.query(User).all()
        stats = db.query(GymStatistics).first()
    
    return Titled(
        "Admin Dashboard - Gymtastic",
        navbar(user.full_name, user.role),
        Div(
            Div(
                H2("Admin Dashboard", cls="text-3xl font-bold mb-6"),
                Div(
                    Div(
                        P(len(users), cls="text-3xl font-bold"),
                        P("Total Users", cls="opacity-70"),
                        cls="stat"
                    ),
                    Div(
                        P(stats.current_occupancy if stats else 0, cls="text-3xl font-bold"),
                        P("Current Occupancy", cls="opacity-70"),
                        cls="stat"
                    ),
                    cls="stats shadow"
                ),
                admin_user_table(users),
                cls="space-y-6"
            ),
            cls="p-6 max-w-4xl mx-auto"
        ),
    )


# ============================================================================
# HTMX ENDPOINTS (DYNAMIC UPDATES)
# ============================================================================

@rt("/get-trainers")
def get_trainers(request: Request):
    """HTMX endpoint to fetch and display trainers."""
    with Session(engine) as db:
        trainers = db.query(Trainer).all()
    return trainer_list(trainers)


@rt("/locker/{locker_id}/unlock", methods=["post"])
def unlock_locker(locker_id: int, request: Request):
    """Unlock locker (simulate IoT)."""
    user = get_current_user(request)
    if not user:
        return alert("Not authenticated", "error")
    
    with Session(engine) as db:
        locker = db.query(Locker).filter(Locker.id == locker_id).first()
        if locker:
            locker.status = "unlocked"
            db.add(locker)
            db.commit()
            return Div(
                alert("✓ Locker unlocked successfully!", "success"),
                P("Your locker is open. (Simulated)", cls="text-sm opacity-70 mt-2"),
                cls="space-y-2"
            )
    return alert("Locker not found", "error")


@rt("/congestion")
def get_congestion(request: Request):
    """HTMX endpoint for real-time congestion."""
    with Session(engine) as db:
        stats = db.query(GymStatistics).first()
        if not stats:
            stats = GymStatistics(current_occupancy=0, total_capacity=100)
            db.add(stats)
            db.commit()
    
    return congestion_widget(stats.current_occupancy, stats.total_capacity)


@rt("/book-trainer/{trainer_id}", methods=["get", "post"])
def book_trainer(trainer_id: int, request: Request, scheduled_at: str = "", duration: int = 60):
    """Book a trainer session."""
    user = get_current_user(request)
    if not user or user.role != "member":
        return alert("Only members can book trainers", "error")
    
    if not scheduled_at:
        # GET: Show booking form
        with Session(engine) as db:
            trainer = db.query(Trainer).filter(Trainer.id == trainer_id).first()
            if not trainer:
                return alert("Trainer not found", "error")
        
        return Form(
            Div(
                H3(f"Book {trainer.user.full_name}", cls="text-lg font-bold mb-4"),
                Div(
                    Label("Date & Time", cls="label"),
                    Input(type="datetime-local", name="scheduled_at", 
                          required=True, cls="input input-bordered w-full"),
                    cls="form-control mb-4"
                ),
                Div(
                    Label("Duration (minutes)", cls="label"),
                    Input(type="number", name="duration", value="60",
                          min="30", max="120", cls="input input-bordered w-full"),
                    cls="form-control mb-4"
                ),
                Button("Confirm Booking", type="submit", cls="btn btn-primary"),
                cls="card-body space-y-4"
            ),
            method="post",
            action=f"/book-trainer/{trainer_id}",
            id="booking-form",
            cls="card bg-base-100 shadow"
        )
    
    # POST: Create booking
    with Session(engine) as db:
        member = db.query(Member).filter(Member.user_id == user.id).first()
        
        new_booking = Booking(
            member_id=member.id,
            trainer_id=trainer_id,
            user_member_id=user.id,
            scheduled_at=datetime.fromisoformat(scheduled_at),
            duration_minutes=duration,
            status="confirmed"
        )
        db.add(new_booking)
        db.commit()
    
    return alert("✓ Booking confirmed! You're scheduled with the trainer.", "success")


# ============================================================================
# STARTUP
# ============================================================================

# Initialize database on module load (before serving)
init_db()


if __name__ == "__main__":
    serve()
