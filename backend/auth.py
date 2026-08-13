"""
auth.py
-------
Real password hashing (Werkzeug's scrypt-based hasher — salted,
industry-standard, ships with Flask so there's nothing extra to install)
and JWT-based session tokens (via PyJWT).

Why JWT instead of server-side sessions: this backend is meant to sit
behind a separately-hosted frontend (Netlify can't run the Flask process —
see the deployment note in the README), so the frontend and backend live
on different origins. A signed token the frontend stores and sends back
in an Authorization header is the standard way to handle that; cross-origin
cookies would need extra SameSite/CORS configuration for no real benefit
here.
"""
import os
import re
import jwt
import datetime
from functools import wraps
from typing import Optional
from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash

# In production, set JWT_SECRET_KEY as a real environment variable —
# this fallback is fine for local development ONLY. If you deploy with
# the fallback still active, every token becomes forgeable.
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-only-insecure-secret-change-me")
TOKEN_EXPIRY_HOURS = 24 * 7  # 1 week

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def validate_signup_fields(username: str, email: str, password: str) -> Optional[str]:
    if not username or not USERNAME_RE.match(username):
        return "Username must be 3-32 characters: letters, numbers, underscore, dot, or hyphen."
    if not email or not EMAIL_RE.match(email):
        return "Enter a valid email address."
    if not password or len(password) < 6:
        return "Password must be at least 6 characters."
    return None


def create_token(user_id: int, username: str) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXPIRY_HOURS),
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token: str):
    return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])


def require_auth(f):
    """Flask route decorator: requires a valid 'Authorization: Bearer <token>' header.
    On success, sets g.user_id and g.username for the route to use."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or malformed Authorization header."}), 401
        token = auth_header[len("Bearer "):].strip()
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Session expired. Log in again."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token."}), 401
        g.user_id = payload["user_id"]
        g.username = payload["username"]
        return f(*args, **kwargs)
    return wrapper
