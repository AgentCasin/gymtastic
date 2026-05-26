"""
Database initialization and connection management.
Handles SQLite setup with SQLModel.
"""

from sqlmodel import Session, SQLModel, create_engine

from models import Booking, GymStatistics, Locker, Member, Payment, Trainer, User

DB_URL = "sqlite:///./gymtastic.db"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})


def init_db():
    """Create tables and seed initial data."""
    SQLModel.metadata.create_all(engine)
    seed_data()


def get_session():
    """Get a database session for dependency injection."""
    with Session(engine) as session:
        yield session


def seed_data():
    """Populate database with dummy data for testing."""
    import hashlib
    from datetime import datetime, timedelta

    with Session(engine) as session:
        # Check if data already seeded
        existing_admin = session.query(User).filter(User.role == "admin").first()
        if existing_admin:
            return

        # Hash passwords (simple hash for demo purposes)
        def hash_pwd(pwd: str) -> str:
            return hashlib.sha256(pwd.encode()).hexdigest()

        # Create Admin
        admin = User(
            email="admin@gymtastic.com",
            password_hash=hash_pwd("admin123"),
            role="admin",
            full_name="Admin User"
        )
        session.add(admin)
        session.flush()

        # Create Trainer
        trainer_user = User(
            email="trainer@gymtastic.com",
            password_hash=hash_pwd("trainer123"),
            role="trainer",
            full_name="John Trainer"
        )
        session.add(trainer_user)
        session.flush()

        trainer = Trainer(
            user_id=trainer_user.id,
            specialization="strength_training",
            hourly_rate=75.0
        )
        session.add(trainer)
        session.flush()

        # Create Members
        member1_user = User(
            email="member1@gymtastic.com",
            password_hash=hash_pwd("member123"),
            role="member",
            full_name="Alice Member"
        )
        session.add(member1_user)
        session.flush()

        member1 = Member(
            user_id=member1_user.id,
            membership_type="premium"
        )
        session.add(member1)
        session.flush()

        member2_user = User(
            email="member2@gymtastic.com",
            password_hash=hash_pwd("member123"),
            role="member",
            full_name="Bob Member"
        )
        session.add(member2_user)
        session.flush()

        member2 = Member(
            user_id=member2_user.id,
            membership_type="basic"
        )
        session.add(member2)
        session.flush()

        # Create Lockers
        locker1 = Locker(locker_number=1, status="available", member_id=member1.id)
        locker2 = Locker(locker_number=2, status="available")
        session.add_all([locker1, locker2])
        session.flush()

        # Locker1 already references member1 via member_id; no further assignment needed

        # Create Booking (future booking for demo)
        tomorrow = datetime.utcnow() + timedelta(days=1)
        booking = Booking(
            member_id=member1.id,
            trainer_id=trainer.id,
            user_member_id=member1_user.id,
            scheduled_at=tomorrow,
            duration_minutes=60,
            status="confirmed"
        )
        session.add(booking)
        session.flush()

        # Create Payment record
        payment = Payment(
            user_id=member1_user.id,
            booking_id=booking.id,
            amount=75.0,
            status="completed",
            payment_method="card"
        )
        session.add(payment)

        # Create Gym Statistics
        stats = GymStatistics(
            current_occupancy=15,
            total_capacity=100
        )
        session.add(stats)

        session.commit()
