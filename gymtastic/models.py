"""
Database models for Gymtastic application.
Uses SQLModel for ORM with SQLite backend.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    """Base user model for all user types."""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    role: str = Field(index=True)  # 'admin', 'trainer', 'member'
    full_name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    member: Optional["Member"] = Relationship(back_populates="user")
    trainer: Optional["Trainer"] = Relationship(back_populates="user")
    bookings: list["Booking"] = Relationship(back_populates="member_user")


class Member(SQLModel, table=True):
    """Member profile with locker and booking info."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    membership_type: str = Field(default="basic")  # 'basic', 'premium', 'vip'
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    user: User = Relationship(back_populates="member")
    # One-to-one: Locker references Member via Locker.member_id
    locker: Optional["Locker"] = Relationship(back_populates="member", sa_relationship_kwargs={"uselist": False})
    bookings: list["Booking"] = Relationship(back_populates="member")


class Trainer(SQLModel, table=True):
    """Trainer profile with availability and specialization."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    specialization: str = Field(default="general")
    hourly_rate: float = Field(default=50.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    user: User = Relationship(back_populates="trainer")
    bookings: list["Booking"] = Relationship(back_populates="trainer")


class Booking(SQLModel, table=True):
    """Session booking between member and trainer."""
    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="member.id")
    trainer_id: int = Field(foreign_key="trainer.id")
    user_member_id: int = Field(foreign_key="user.id")  # For member user lookup
    scheduled_at: datetime
    duration_minutes: int = Field(default=60)
    status: str = Field(default="pending")  # 'pending', 'confirmed', 'completed', 'cancelled'
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    member: Member = Relationship(back_populates="bookings")
    trainer: Trainer = Relationship(back_populates="bookings")
    member_user: User = Relationship(back_populates="bookings")


class Locker(SQLModel, table=True):
    """Smart locker with RFID/IoT integration."""
    id: Optional[int] = Field(default=None, primary_key=True)
    locker_number: int = Field(unique=True, index=True)
    status: str = Field(default="available")  # 'available', 'occupied', 'locked'
    member_id: Optional[int] = Field(foreign_key="member.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    member: Optional[Member] = Relationship(back_populates="locker")


class Payment(SQLModel, table=True):
    """Payment transaction record."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    booking_id: Optional[int] = Field(foreign_key="booking.id")
    amount: float
    status: str = Field(default="pending")  # 'pending', 'completed', 'failed'
    payment_method: str = Field(default="card")  # 'card', 'wallet', 'cash'
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class GymStatistics(SQLModel, table=True):
    """Real-time gym statistics for congestion tracking."""
    id: Optional[int] = Field(default=None, primary_key=True)
    current_occupancy: int = Field(default=0)
    total_capacity: int = Field(default=100)
    peak_hours: str = Field(default="17:00-19:00")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
