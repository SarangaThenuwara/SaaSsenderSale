import time
import hashlib
from collections import defaultdict


class AuthenticationManager:
    def __init__(self):
        self.user_data = defaultdict(dict)  # Holds user authentication data
        self.rate_limit_data = defaultdict(list)  # Holds timestamps for rate limiting
        self.lockout_time = 300  # Lockout time in seconds
        self.max_login_attempts = 5

    def validate_password(self, password):
        # Validate password strength
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not any(char.isdigit() for char in password):
            raise ValueError("Password must contain at least one digit.")
        if not any(char.isalpha() for char in password):
            raise ValueError("Password must contain at least one letter.")
        return True

    def hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    def register_user(self, username, password):
        if username in self.user_data:
            raise ValueError("User already exists.")
        self.validate_password(password)
        self.user_data[username]["password"] = self.hash_password(password)
        self.user_data[username]["failed_attempts"] = 0
        self.user_data[username]["lockout_until"] = 0.0

    def login(self, username, password):
        current_time = time.time()
        if username in self.rate_limit_data:
            # Check for rate limiting
            self.rate_limit_data[username] = [
                ts for ts in self.rate_limit_data[username] if ts > current_time - 60
            ]
            if len(self.rate_limit_data[username]) >= self.max_login_attempts:
                raise ValueError("Too many login attempts. Please try again later.")

        if username not in self.user_data:
            raise ValueError("Username not found.")

        user = self.user_data[username]
        lockout_until = user.get("lockout_until", 0.0)

        if lockout_until and current_time < lockout_until:
            raise ValueError("Account is locked. Please try again later.")

        if user["password"] == self.hash_password(password):
            user["failed_attempts"] = 0
            user["lockout_until"] = 0.0
            print("Login successful!")
        else:
            user["failed_attempts"] += 1
            self.rate_limit_data[username].append(current_time)
            if user["failed_attempts"] >= self.max_login_attempts:
                user["lockout_until"] = current_time + self.lockout_time
                raise ValueError(
                    "Account locked due to too many failed attempts. Please try again later."
                )
            raise ValueError("Invalid password.")

    def unlock_account(self, username):
        if username in self.user_data:
            self.user_data[username]["lockout_until"] = 0.0
            self.user_data[username]["failed_attempts"] = 0
            return "Account unlocked."
        return "Username not found."