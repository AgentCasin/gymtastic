"""
Reusable UI components built with MonsterUI for Gymtastic.
Centralizes component definitions to keep main.py clean.
"""

from fasthtml.common import *
from monsterui.all import *


def navbar(user_name: str = "Guest", role: str = "") -> Div:
    """Main navigation bar."""
    return Nav(
        Div(
            A("Gymtastic", href="/", cls="text-lg font-bold"),
            cls="flex items-center flex-1"
        ),
        Div(
            Span(f"{user_name} ({role})", cls="text-sm mr-4"),
            A("Logout", href="/logout", cls="btn btn-sm btn-outline"),
            cls="flex items-center gap-2"
        ),
        cls="navbar bg-base-200 shadow"
    )


def login_form() -> Form:
    """Login form component."""
    return Form(
        Div(
            H1("Login to Gymtastic", cls="text-2xl font-bold mb-6"),
            Div(
                Label("Email", cls="label"),
                Input(type="email", name="email", placeholder="your@email.com", 
                      required=True, cls="input input-bordered w-full"),
                cls="form-control w-full mb-4"
            ),
            Div(
                Label("Password", cls="label"),
                Input(type="password", name="password", placeholder="Enter password",
                      required=True, cls="input input-bordered w-full"),
                cls="form-control w-full mb-6"
            ),
            Button("Sign In", type="submit", cls="btn btn-primary w-full"),
            P(A("Create Account", href="/register", cls="link link-primary"), 
              cls="text-center mt-4"),
            cls="card-body"
        ),
        method="post",
        action="/login",
        cls="card bg-base-100 shadow-xl max-w-md mx-auto mt-10"
    )


def register_form() -> Form:
    """Registration form component."""
    return Form(
        Div(
            H1("Create Account", cls="text-2xl font-bold mb-6"),
            Div(
                Label("Full Name", cls="label"),
                Input(type="text", name="full_name", placeholder="Your full name",
                      required=True, cls="input input-bordered w-full"),
                cls="form-control w-full mb-4"
            ),
            Div(
                Label("Email", cls="label"),
                Input(type="email", name="email", placeholder="your@email.com",
                      required=True, cls="input input-bordered w-full"),
                cls="form-control w-full mb-4"
            ),
            Div(
                Label("Password", cls="label"),
                Input(type="password", name="password", placeholder="Min 6 chars",
                      required=True, cls="input input-bordered w-full"),
                cls="form-control w-full mb-4"
            ),
            Div(
                Label("Account Type", cls="label"),
                Select(
                    Option("member", value="member"),
                    Option("trainer", value="trainer"),
                    name="role",
                    cls="select select-bordered w-full"
                ),
                cls="form-control w-full mb-6"
            ),
            Button("Create Account", type="submit", cls="btn btn-primary w-full"),
            P(A("Already have account?", href="/login", cls="link link-primary"),
              cls="text-center mt-4"),
            cls="card-body"
        ),
        method="post",
        action="/register",
        cls="card bg-base-100 shadow-xl max-w-md mx-auto mt-10"
    )


def member_dashboard_card(full_name: str, membership: str) -> Div:
    """Member profile card on dashboard."""
    return Div(
        Div(
            H3(full_name, cls="text-xl font-bold"),
            P(f"Membership: {membership}", cls="text-sm opacity-70"),
            cls="card-body"
        ),
        cls="card bg-base-100 shadow"
    )


def booking_card(trainer_name: str, scheduled_at: str, status: str) -> Div:
    """Booking info card."""
    status_color = "badge-success" if status == "confirmed" else "badge-warning"
    return Div(
        Div(
            Div(
                P(f"Trainer: {trainer_name}", cls="font-semibold"),
                P(f"When: {scheduled_at}", cls="text-sm opacity-70"),
                cls="flex-1"
            ),
            Span(status.capitalize(), cls=f"badge {status_color}"),
            cls="flex justify-between items-center"
        ),
        cls="card bg-base-100 shadow p-4 mb-3"
    )


def locker_unlock_button(locker_id: int, locker_number: int) -> Div:
    """Smart locker unlock button with HTMX."""
    return Div(
        P(f"Locker #{locker_number}", cls="font-semibold mb-3"),
        Button(
            "🔓 Unlock Locker",
            hx_post=f"/locker/{locker_id}/unlock",
            hx_target="#locker-status",
            hx_swap="innerHTML",
            cls="btn btn-success"
        ),
        Div(id="locker-status", cls="mt-3 text-sm"),
        cls="card bg-base-100 shadow p-4"
    )


def congestion_widget(occupancy: int, capacity: int) -> Div:
    """Real-time congestion display with HTMX auto-refresh."""
    percentage = int((occupancy / capacity) * 100) if capacity > 0 else 0
    congestion_level = "Low"
    color_class = "progress-success"
    
    if percentage > 70:
        congestion_level = "High"
        color_class = "progress-error"
    elif percentage > 40:
        congestion_level = "Medium"
        color_class = "progress-warning"
    
    return Div(
        Div(
            H4("Gym Congestion", cls="font-bold mb-3"),
            P(f"{occupancy} / {capacity} Members", cls="text-sm opacity-70 mb-2"),
            Progress(value=occupancy, max=capacity, cls=f"progress {color_class} w-full mb-2"),
            P(f"Status: {congestion_level}", cls="text-sm font-semibold"),
            Button(
                "🔄 Refresh",
                hx_get="/congestion",
                hx_target="#congestion-widget",
                hx_swap="outerHTML",
                cls="btn btn-sm btn-outline mt-3"
            ),
            cls="card-body"
        ),
        id="congestion-widget",
        cls="card bg-base-100 shadow",
        hx_trigger="load, every 30s"
    )


def trainer_list(trainers: list) -> Div:
    """List of available trainers for booking."""
    trainer_items = [
        Div(
            Div(
                P(trainer.user.full_name, cls="font-semibold"),
                P(f"{trainer.specialization}", cls="text-sm opacity-70"),
                P(f"${trainer.hourly_rate}/hr", cls="text-sm font-semibold text-success"),
                cls="flex-1"
            ),
            Button(
                "Book",
                hx_get=f"/book-trainer/{trainer.id}",
                hx_target="#booking-form",
                hx_swap="outerHTML",
                cls="btn btn-sm btn-primary"
            ),
            cls="flex justify-between items-center card bg-base-100 shadow p-4 mb-3"
        )
        for trainer in trainers
    ]
    
    return Div(
        H3("Available Trainers", cls="text-lg font-bold mb-4"),
        Div(*trainer_items),
        cls="space-y-3"
    )


def admin_user_table(users: list) -> Div:
    """Admin dashboard: user management table."""
    rows = [
        Tr(
            Td(user.full_name),
            Td(user.email),
            Td(Span(user.role.capitalize(), cls="badge badge-outline")),
            Td(A("Edit", href=f"/admin/edit-user/{user.id}", cls="link link-primary")),
            cls="hover"
        )
        for user in users
    ]
    
    return Div(
        H3("User Management", cls="text-lg font-bold mb-4"),
        Table(
            Thead(
                Tr(
                    Th("Name"),
                    Th("Email"),
                    Th("Role"),
                    Th("Actions")
                )
            ),
            Tbody(*rows),
            cls="table table-compact w-full"
        ),
        cls="card bg-base-100 shadow p-4"
    )


def alert(message: str, alert_type: str = "info") -> Div:
    """Alert/toast notification."""
    icon_map = {
        "success": "✓",
        "error": "✕",
        "warning": "⚠",
        "info": "ℹ"
    }
    alert_class = f"alert alert-{alert_type}"
    return Div(
        Span(f"{icon_map.get(alert_type, 'ℹ')} {message}"),
        cls=alert_class
    )
