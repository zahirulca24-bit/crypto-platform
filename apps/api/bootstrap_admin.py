import argparse
import getpass
import sys
from sqlalchemy.orm import Session
from database import SessionLocal
from models import User
from security import hash_password

def main():
    parser = argparse.ArgumentParser(description="Bootstrap an admin user for the application.")
    parser.add_argument("--email", required=True, help="Email address of the admin user to create")
    args = parser.parse_args()

    email = args.email.strip().lower()

    password = getpass.getpass(prompt=f"Enter password for admin {email}: ")
    confirm_password = getpass.getpass(prompt="Confirm password: ")

    if password != confirm_password:
        print("Error: Passwords do not match.")
        sys.exit(1)

    if len(password) < 8:
        print("Error: Password must be at least 8 characters long.")
        sys.exit(1)

    db: Session = SessionLocal()
    try:
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            print(f"User {email} already exists.")
            sys.exit(1)

        hashed_pwd = hash_password(password)

        user = User(
            email=email,
            password_hash=hashed_pwd,
            display_name="Administrator",
            timezone="UTC",
            base_currency="USDT",
            status="active",
            role="admin",
        )
        db.add(user)
        db.commit()
        print(f"Successfully created admin user: {email}")

    except Exception as e:
        print(f"Error creating admin user: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
