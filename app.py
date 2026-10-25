"""
app.py - Bicycle Rental Management System
Flask backend with full authentication, session management, and route protection.
"""

import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
import re

# ─────────────────────────────────────────
# App Initialisation
# ─────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "bicycle_rental_secret_key"
# ─────────────────────────────────────────
# Database Configuration
# ─────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": os.environ.get("DB_PASSWORD", "Shadil@12"),  # env var preferred, falls back to local
    "database": "bicycle_rental_db",
    "charset":  "utf8mb4",
}


def get_db_connection():
    """Return a fresh MySQL connection, or None on failure."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"[DB ERROR] {e}")
        return None


def query(sql, params=None, fetch="all"):
    """
    Utility: run a SELECT query and return rows.
    fetch='all' → list of dicts | fetch='one' → single dict | fetch=None → rowcount
    """
    conn = get_db_connection()
    if conn is None:
        return [] if fetch == "all" else None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        if fetch == "all":
            return cursor.fetchall()
        elif fetch == "one":
            return cursor.fetchone()
        else:
            conn.commit()
            return cursor.rowcount
    except Error as e:
        print(f"[QUERY ERROR] {e}")
        return [] if fetch == "all" else None
    finally:
        cursor.close()
        conn.close()


def execute(sql, params=None):
    """Utility: run INSERT / UPDATE / DELETE queries. Returns last insert ID or False."""
    conn = get_db_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()
        return cursor.lastrowid or True
    except Error as e:
        print(f"[EXECUTE ERROR] {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


# ─────────────────────────────────────────────────────────────
# AUTH DECORATORS
# ─────────────────────────────────────────────────────────────

def student_required(f):
    """Protect routes that require a logged-in student."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("user_type") != "student" or not session.get("student_id"):
            flash("Please log in to access the student portal.", "error")
            return redirect(url_for("student_login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Protect routes that require a logged-in staff/admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("user_type") != "staff" or not session.get("staff_id"):
            flash("Staff login required to access the admin panel.", "error")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def validate_email(email):
    return re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) is not None

def validate_phone(phone):
    return re.match(r'^\d{10}$', phone) is not None if phone else True

def auto_sync_status():
    """
    Automatically synchronize fleet status:
    1. Expire pending reservations past their 2-hour window and restore the bicycles to 'available'.
    2. Mark active rentals past their due date as 'overdue'.
    """
    try:
        execute("""
            UPDATE bicycles b
            JOIN reservations r ON b.bicycle_id = r.bicycle_id
            SET b.status = 'available'
            WHERE r.status IN ('pending', 'confirmed') AND r.expires_at < NOW() AND b.status = 'reserved'
        """)
        execute("""
            UPDATE reservations
            SET status = 'cancelled'
            WHERE status IN ('pending', 'confirmed') AND expires_at < NOW()
        """)
        execute("""
            UPDATE rentals
            SET status = 'overdue'
            WHERE status = 'active' AND due_at < NOW()
        """)
    except Exception as e:
        print(f"[AUTO-SYNC] {e}")


# ─────────────────────────────────────────────────────────────
# HERO / LANDING PAGE
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Hero landing page."""
    return render_template("index.html")


# ─────────────────────────────────────────────────────────────
# STUDENT AUTH
# ─────────────────────────────────────────────────────────────

@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    """Student login page."""
    if session.get("user_type") == "student":
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password   = request.form.get("password", "")

        if not identifier or not password:
            flash("Please fill in all fields.", "error")
            return render_template("student_login.html")

        # Allow login by email OR roll number
        student = query(
            "SELECT * FROM students WHERE email = %s OR roll_number = %s",
            (identifier, identifier), fetch="one"
        )

        if not student:
            flash("No account found with that email or roll number.", "error")
            return render_template("student_login.html")

        if not student.get("password_hash"):
            flash("Your account has no password set. Please register first.", "error")
            return render_template("student_login.html")

        if not check_password_hash(student["password_hash"], password):
            flash("Incorrect password. Please try again.", "error")
            return render_template("student_login.html")

        # Success — set session
        session.clear()
        session["user_type"]    = "student"
        session["student_id"]   = student["student_id"]
        session["student_name"] = student["name"]
        session["student_roll"] = student["roll_number"]
        session.permanent = True

        flash(f"Welcome back, {student['name'].split()[0]}! 🎉", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("student_dashboard"))

    return render_template("student_login.html")


@app.route("/student/register", methods=["GET", "POST"])
def student_register():
    """Student registration page."""
    if session.get("user_type") == "student":
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":
        name        = request.form.get("name", "").strip()
        email       = request.form.get("email", "").strip().lower()
        phone       = request.form.get("phone", "").strip()
        roll_number = request.form.get("roll_number", "").strip().upper()
        password    = request.form.get("password", "")
        confirm_pw  = request.form.get("confirm_password", "")

        # Validation
        errors = []
        if not name or len(name) < 2:
            errors.append("Please enter your full name.")
        if not email or not validate_email(email):
            errors.append("Please enter a valid email address.")
        if not roll_number:
            errors.append("Roll number is required.")
        if phone and not validate_phone(phone):
            errors.append("Phone must be 10 digits.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm_pw:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("student_register.html",
                form_data={"name": name, "email": email, "phone": phone, "roll_number": roll_number})

        # Check duplicates
        existing = query(
            "SELECT student_id FROM students WHERE email = %s OR roll_number = %s",
            (email, roll_number), fetch="one"
        )
        if existing:
            flash("An account with this email or roll number already exists.", "error")
            return render_template("student_register.html",
                form_data={"name": name, "email": email, "phone": phone, "roll_number": roll_number})

        ph = generate_password_hash(password)
        ok = execute(
            "INSERT INTO students (name, email, phone, roll_number, password_hash) VALUES (%s,%s,%s,%s,%s)",
            (name, email, phone or None, roll_number, ph)
        )
        if ok:
            student_id = ok
            session.clear()
            session["user_type"]    = "student"
            session["student_id"]   = student_id
            session["student_name"] = name
            session["student_roll"] = roll_number
            session.permanent = True
            flash(f"Account created! Welcome to CampusCycle, {name.split()[0]}! 🎉", "success")
            return redirect(url_for("student_dashboard"))
        else:
            flash("Registration failed. Please try again.", "error")

    return render_template("student_register.html", form_data={})


@app.route("/student/logout")
def student_logout():
    """Log out the student."""
    name = session.get("student_name", "Student")
    session.clear()
    flash(f"You've been logged out. See you soon, {name.split()[0]}!", "success")
    return redirect(url_for("student_login"))


# ─────────────────────────────────────────────────────────────
# ADMIN AUTH
# ─────────────────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin/staff login page."""
    if session.get("user_type") == "staff":
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please fill in all fields.", "error")
            return render_template("admin_login.html")

        staff = query(
            "SELECT * FROM staff WHERE email = %s", (email,), fetch="one"
        )

        if not staff:
            flash("No staff account found with that email.", "error")
            return render_template("admin_login.html")

        if not check_password_hash(staff["password_hash"], password):
            flash("Incorrect password.", "error")
            return render_template("admin_login.html")

        session.clear()
        session["user_type"]  = "staff"
        session["staff_id"]   = staff["staff_id"]
        session["staff_name"] = staff["name"]
        session["staff_role"] = staff["role"]
        session.permanent = True

        flash(f"Welcome back, {staff['name'].split()[0]}! 🛠️", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("admin_dashboard"))

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    """Log out the admin/staff."""
    name = session.get("staff_name", "Admin")
    session.clear()
    flash(f"Logged out successfully. Goodbye, {name.split()[0]}!", "success")
    return redirect(url_for("admin_login"))


# ─────────────────────────────────────────────────────────────
# STUDENT PORTAL  (all routes now session-protected)
# ─────────────────────────────────────────────────────────────

@app.route("/student")
@student_required
def student_dashboard():
    """Student Dashboard – summary cards."""
    auto_sync_status()
    student_id = session["student_id"]

    student = query("SELECT * FROM students WHERE student_id = %s", (student_id,), fetch="one")

    available_count = query("SELECT COUNT(*) AS cnt FROM bicycles WHERE status = 'available'", fetch="one")
    active_rentals  = query(
        "SELECT COUNT(*) AS cnt FROM rentals WHERE student_id = %s AND status = 'active'",
        (student_id,), fetch="one"
    )
    overdue_rentals = query(
        "SELECT COUNT(*) AS cnt FROM rentals WHERE student_id = %s AND status = 'overdue'",
        (student_id,), fetch="one"
    )
    pending_reservations = query(
        "SELECT COUNT(*) AS cnt FROM reservations WHERE student_id = %s AND status IN ('pending','confirmed')",
        (student_id,), fetch="one"
    )

    return render_template(
        "student_dashboard.html",
        student=student,
        available_count=available_count["cnt"] if available_count else 0,
        active_rentals=active_rentals["cnt"] if active_rentals else 0,
        overdue_rentals=overdue_rentals["cnt"] if overdue_rentals else 0,
        pending_reservations=pending_reservations["cnt"] if pending_reservations else 0,
    )


@app.route("/student/bikes")
@student_required
def student_bikes():
    """Browse Bicycles & Stations – real-time availability."""
    auto_sync_status()
    student_id  = session["student_id"]
    type_filter = request.args.get("type", "all")

    if type_filter != "all":
        bikes = query(
            """SELECT b.bicycle_id, b.model, b.type, b.status,
                      s.station_id, s.name AS station_name, s.location
               FROM bicycles b
               JOIN stations s ON b.station_id = s.station_id
               WHERE b.status = 'available' AND b.type = %s
               ORDER BY s.name, b.type""",
            (type_filter,),
        )
    else:
        bikes = query(
            """SELECT b.bicycle_id, b.model, b.type, b.status,
                      s.station_id, s.name AS station_name, s.location
               FROM bicycles b
               JOIN stations s ON b.station_id = s.station_id
               WHERE b.status = 'available'
               ORDER BY s.name, b.type"""
        )

    stations = query(
        """SELECT s.station_id, s.name, s.location, s.capacity,
                  SUM(CASE WHEN b.status = 'available' THEN 1 ELSE 0 END) AS available,
                  COUNT(b.bicycle_id) AS total
           FROM stations s
           LEFT JOIN bicycles b ON s.station_id = b.station_id
           GROUP BY s.station_id
           ORDER BY s.name"""
    )

    return render_template("student_bikes.html", bikes=bikes, stations=stations, type_filter=type_filter)


@app.route("/student/reserve/<int:bicycle_id>", methods=["POST"])
@student_required
def reserve_bicycle(bicycle_id):
    """Create a reservation for a bicycle (expires in 2 hours)."""
    auto_sync_status()
    student_id = session["student_id"]
    expires_at = datetime.now() + timedelta(hours=2)

    # Check for an existing active or overdue rental
    existing_rental = query(
        "SELECT rental_id FROM rentals WHERE student_id = %s AND status IN ('active', 'overdue')",
        (student_id,), fetch="one"
    )
    if existing_rental:
        flash("You already have an active or overdue bicycle rental. Please return it before reserving another.", "error")
        return redirect(url_for("student_notifications"))

    existing_res = query(
        "SELECT reservation_id FROM reservations WHERE student_id = %s AND status IN ('pending','confirmed')",
        (student_id,), fetch="one"
    )
    if existing_res:
        flash("You already have an active reservation. Cancel it before making a new one.", "error")
        return redirect(url_for("student_notifications"))

    # Check bike is still available (with row-level check)
    bike = query(
        "SELECT * FROM bicycles WHERE bicycle_id = %s AND status = 'available'",
        (bicycle_id,), fetch="one"
    )
    if not bike:
        flash("This bicycle is no longer available. Please choose another.", "error")
        return redirect(url_for("student_bikes"))

    station_id = bike["station_id"]

    # Atomic: mark bike reserved then insert reservation
    ok_bike = execute(
        "UPDATE bicycles SET status = 'reserved' WHERE bicycle_id = %s AND status = 'available'",
        (bicycle_id,)
    )
    if not ok_bike:
        flash("Bicycle was just taken. Please choose another.", "error")
        return redirect(url_for("student_bikes"))

    ok_res = execute(
        """INSERT INTO reservations (student_id, bicycle_id, station_id, expires_at, status)
           VALUES (%s, %s, %s, %s, 'pending')""",
        (student_id, bicycle_id, station_id, expires_at),
    )
    if not ok_res:
        # Rollback bike status
        execute("UPDATE bicycles SET status = 'available' WHERE bicycle_id = %s", (bicycle_id,))
        flash("Reservation failed. Please try again.", "error")
        return redirect(url_for("student_bikes"))

    flash("Reservation placed! 🎉 Pick up within 2 hours at the station.", "success")
    return redirect(url_for("student_notifications"))


@app.route("/student/unreserve/<int:reservation_id>", methods=["POST"])
@student_required
def unreserve_bicycle(reservation_id):
    """Cancel a reservation – student must own it."""
    student_id = session["student_id"]

    reservation = query(
        "SELECT * FROM reservations WHERE reservation_id = %s AND student_id = %s",
        (reservation_id, student_id), fetch="one"
    )

    if not reservation:
        flash("Reservation not found or access denied.", "error")
        return redirect(url_for("student_notifications"))

    if reservation["status"] not in ("pending", "confirmed"):
        flash("This reservation can no longer be cancelled.", "error")
        return redirect(url_for("student_notifications"))

    ok = execute(
        "UPDATE reservations SET status = 'cancelled' WHERE reservation_id = %s",
        (reservation_id,)
    )
    if ok:
        execute(
            "UPDATE bicycles SET status = 'available' WHERE bicycle_id = %s AND status = 'reserved'",
            (reservation["bicycle_id"],)
        )
        flash("Reservation cancelled. Bicycle is now available again.", "success")
    else:
        flash("Failed to cancel reservation. Please try again.", "error")

    return redirect(url_for("student_notifications"))

@app.route("/student/reservation/cancel/<int:reservation_id>", methods=["POST"])
def cancel_reservation(reservation_id):
    """
    Allow a student to cancel their own active bicycle reservation.
    Verifies reservation ownership, updates status to 'cancelled',
    and releases the bicycle back to 'available'.
    """
    student_id = request.form.get("student_id", type=int)
    if not student_id:
        student_id = request.args.get("student_id", 1, type=int)

    # Fetch reservation details
    res = query(
        "SELECT * FROM reservations WHERE reservation_id = %s",
        (reservation_id,),
        fetch="one",
    )

    if not res:
        flash("Reservation not found.", "error")
        return redirect(url_for("student_notifications", student_id=student_id))

    # Security check: Ensure students can ONLY cancel their own reservation
    if res["student_id"] != student_id:
        flash("Unauthorized: You can only cancel your own cycle reservation.", "error")
        return redirect(url_for("student_notifications", student_id=student_id))

    # Check if the reservation is in a cancellable state
    if res["status"] not in ("pending", "confirmed"):
        flash(
            f"Reservation #{reservation_id} is already marked as {res['status']} and cannot be cancelled.",
            "warning",
        )
        return redirect(url_for("student_notifications", student_id=student_id))

    # 1. Update reservation status to cancelled
    cancelled = execute(
        "UPDATE reservations SET status = 'cancelled' WHERE reservation_id = %s AND student_id = %s",
        (reservation_id, student_id),
    )

    if cancelled:
        # 2. Release bicycle back to available if it is currently marked as reserved
        execute(
            "UPDATE bicycles SET status = 'available' WHERE bicycle_id = %s AND status = 'reserved'",
            (res["bicycle_id"],),
        )
        flash(
            f"Reservation #{reservation_id} has been cancelled successfully. The bicycle is now available for others.",
            "success",
        )
    else:
        flash("Failed to cancel reservation. Please try again.", "error")

    return redirect(url_for("student_notifications", student_id=student_id))


@app.route("/student/notifications")
@student_required
def student_notifications():
    """My Rentals & Notifications."""
    auto_sync_status()
    student_id = session["student_id"]

    student = query("SELECT * FROM students WHERE student_id = %s", (student_id,), fetch="one")

    rentals = query(
        """SELECT r.rental_id, r.issued_at, r.due_at, r.returned_at, r.status, r.issued_by,
                  b.bicycle_id, b.model, b.type,
                  s.name AS station_name
           FROM rentals r
           JOIN bicycles b ON r.bicycle_id = b.bicycle_id
           JOIN stations s ON b.station_id = s.station_id
           WHERE r.student_id = %s
           ORDER BY r.issued_at DESC""",
        (student_id,),
    )

    reservations = query(
        """SELECT res.reservation_id, res.reserved_at, res.expires_at, res.status,
                  b.bicycle_id, b.model, b.type,
                  s.name AS station_name
           FROM reservations res
           JOIN bicycles b ON res.bicycle_id = b.bicycle_id
           JOIN stations s ON res.station_id = s.station_id
           WHERE res.student_id = %s
           ORDER BY res.reserved_at DESC""",
        (student_id,),
    )

    now = datetime.now()
    return render_template(
        "student_notifications.html",
        student=student,
        rentals=rentals,
        reservations=reservations,
        now=now,
    )


# ─────────────────────────────────────────────────────────────
# ADMIN PANEL  (all routes session-protected)
# ─────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_dashboard():
    """Admin Dashboard – KPI cards and recent activity."""
    auto_sync_status()
    total_stations   = query("SELECT COUNT(*) AS cnt FROM stations", fetch="one")
    total_bikes      = query("SELECT COUNT(*) AS cnt FROM bicycles", fetch="one")
    available_bikes  = query("SELECT COUNT(*) AS cnt FROM bicycles WHERE status='available'", fetch="one")
    active_rentals   = query("SELECT COUNT(*) AS cnt FROM rentals WHERE status='active'", fetch="one")
    overdue_rentals  = query("SELECT COUNT(*) AS cnt FROM rentals WHERE status='overdue'", fetch="one")
    total_students   = query("SELECT COUNT(*) AS cnt FROM students", fetch="one")
    pending_res      = query(
        "SELECT COUNT(*) AS cnt FROM reservations WHERE status IN ('pending', 'confirmed')", fetch="one"
    )

    recent_rentals_list = query(
        """SELECT r.rental_id, 'rental' AS record_type, r.issued_at, r.status,
                  st.name AS student_name, st.roll_number,
                  b.model, b.type
           FROM rentals r
           JOIN students st ON r.student_id = st.student_id
           JOIN bicycles b  ON r.bicycle_id  = b.bicycle_id
           ORDER BY r.issued_at DESC LIMIT 10"""
    )
    recent_res_list = query(
        """SELECT res.reservation_id AS rental_id, 'reservation' AS record_type,
                  res.reserved_at AS issued_at, res.status,
                  st.name AS student_name, st.roll_number,
                  b.model, b.type
           FROM reservations res
           JOIN students st ON res.student_id = st.student_id
           JOIN bicycles b  ON res.bicycle_id  = b.bicycle_id
           ORDER BY res.reserved_at DESC LIMIT 10"""
    )
    recent_activity = (recent_rentals_list or []) + (recent_res_list or [])
    recent_activity.sort(key=lambda x: x["issued_at"] or datetime.min, reverse=True)

    return render_template(
        "admin_dashboard.html",
        total_stations       = total_stations["cnt"]  if total_stations  else 0,
        total_bikes          = total_bikes["cnt"]      if total_bikes     else 0,
        available_bikes      = available_bikes["cnt"]  if available_bikes else 0,
        active_rentals       = active_rentals["cnt"]   if active_rentals  else 0,
        overdue_rentals      = overdue_rentals["cnt"]  if overdue_rentals else 0,
        total_students       = total_students["cnt"]   if total_students  else 0,
        pending_reservations = pending_res["cnt"]      if pending_res     else 0,
        recent_rentals       = recent_activity[:6],
    )


@app.route("/admin/stations")
@admin_required
def admin_stations():
    """Manage Stations & Bikes."""
    auto_sync_status()
    stations = query(
        """SELECT s.station_id, s.name, s.location, s.capacity,
                  SUM(CASE WHEN b.status='available'   THEN 1 ELSE 0 END) AS available,
                  SUM(CASE WHEN b.status='rented'      THEN 1 ELSE 0 END) AS rented,
                  SUM(CASE WHEN b.status='reserved'    THEN 1 ELSE 0 END) AS reserved,
                  SUM(CASE WHEN b.status='maintenance' THEN 1 ELSE 0 END) AS maintenance,
                  COUNT(b.bicycle_id) AS total
           FROM stations s
           LEFT JOIN bicycles b ON s.station_id = b.station_id
           GROUP BY s.station_id
           ORDER BY s.name"""
    )
    bikes = query(
        """SELECT b.bicycle_id, b.model, b.type, b.status, b.added_at,
                  s.name AS station_name
           FROM bicycles b
           JOIN stations s ON b.station_id = s.station_id
           ORDER BY s.name, b.status"""
    )
    return render_template("admin_stations.html", stations=stations, bikes=bikes)


@app.route("/admin/stations/update-status", methods=["POST"])
@admin_required
def update_bike_status():
    """Admin: quickly change a bicycle's status."""
    bicycle_id = request.form.get("bicycle_id", type=int)
    new_status  = request.form.get("status")
    allowed     = {"available", "rented", "maintenance", "reserved"}

    if not bicycle_id or new_status not in allowed:
        flash("Invalid request.", "error")
        return redirect(url_for("admin_stations"))

    # Safety: don't manually set a bike to 'available' if it's currently actively rented
    if new_status in ("available", "reserved"):
        active_rental = query(
            "SELECT rental_id FROM rentals WHERE bicycle_id = %s AND status IN ('active', 'overdue')",
            (bicycle_id,), fetch="one"
        )
        if active_rental:
            flash(f"Cannot set Bike #{bicycle_id} to '{new_status}': it is currently checked out under Rental #{active_rental['rental_id']}. Please process the return first.", "error")
            return redirect(url_for("admin_stations"))

    if new_status in ("available", "maintenance"):
        # Close any active reservation on this bike
        execute(
            "UPDATE reservations SET status='cancelled' WHERE bicycle_id=%s AND status IN ('pending','confirmed')",
            (bicycle_id,)
        )

    execute("UPDATE bicycles SET status = %s WHERE bicycle_id = %s", (new_status, bicycle_id))
    flash(f"Bicycle #{bicycle_id} status updated to '{new_status}'.", "success")
    return redirect(url_for("admin_stations"))


@app.route("/admin/rentals")
@admin_required
def admin_rentals():
    """Rental Records – full list filterable by status."""
    auto_sync_status()
    status_filter = request.args.get("status", "all")

    rentals_base = """
        SELECT r.rental_id AS record_id, r.rental_id, NULL AS reservation_id,
               'rental' AS record_type,
               r.issued_at, r.due_at, r.returned_at, r.status, r.issued_by,
               st.name AS student_name, st.roll_number, st.email,
               b.bicycle_id, b.model, b.type,
               s.name AS station_name
        FROM rentals r
        JOIN students st ON r.student_id = st.student_id
        JOIN bicycles b  ON r.bicycle_id  = b.bicycle_id
        JOIN stations s  ON b.station_id  = s.station_id
    """
    res_base = """
        SELECT res.reservation_id AS record_id, NULL AS rental_id, res.reservation_id,
               'reservation' AS record_type,
               res.reserved_at AS issued_at, res.expires_at AS due_at,
               NULL AS returned_at, res.status, 'Online Reservation' AS issued_by,
               st.name AS student_name, st.roll_number, st.email,
               b.bicycle_id, b.model, b.type,
               s.name AS station_name
        FROM reservations res
        JOIN students st ON res.student_id = st.student_id
        JOIN bicycles b  ON res.bicycle_id  = b.bicycle_id
        JOIN stations s  ON res.station_id  = s.station_id
    """

    if status_filter == "reserved":
        records = query(res_base + " ORDER BY res.reserved_at DESC") or []
    elif status_filter in ("active", "overdue", "returned"):
        records = query(rentals_base + " WHERE r.status = %s ORDER BY r.issued_at DESC", (status_filter,)) or []
    else:
        rentals_all      = query(rentals_base) or []
        reservations_all = query(res_base) or []
        records = rentals_all + reservations_all
        records.sort(key=lambda x: x["issued_at"] or datetime.min, reverse=True)

    res_count = query(
        "SELECT COUNT(*) AS cnt FROM reservations WHERE status IN ('pending', 'confirmed')", fetch="one"
    )
    reserved_count = res_count["cnt"] if res_count else 0

    return render_template(
        "admin_rentals.html",
        rentals=records,
        status_filter=status_filter,
        reserved_count=reserved_count,
    )


@app.route("/admin/rentals/return/<int:rental_id>", methods=["POST"])
@admin_required
def return_rental(rental_id):
    """Admin: mark a rental as returned and free the bicycle."""
    rental = query("SELECT * FROM rentals WHERE rental_id = %s", (rental_id,), fetch="one")
    if rental and rental["status"] in ("active", "overdue"):
        execute(
            "UPDATE rentals SET status='returned', returned_at=NOW() WHERE rental_id=%s", (rental_id,)
        )
        execute("UPDATE bicycles SET status='available' WHERE bicycle_id=%s", (rental["bicycle_id"],))
        flash(f"Rental #{rental_id} marked as returned. Bicycle is now available. ✅", "success")
    else:
        flash("Rental not found or already returned.", "error")
    return redirect(url_for("admin_rentals"))


@app.route("/admin/reservations/issue/<int:reservation_id>", methods=["POST"])
@admin_required
def issue_reservation(reservation_id):
    """Admin: issue a reserved bicycle (converts reservation to active rental)."""
    auto_sync_status()
    res = query("SELECT * FROM reservations WHERE reservation_id = %s", (reservation_id,), fetch="one")
    if res and res["status"] in ("pending", "confirmed"):
        # Prevent double-rental by the same student
        existing_rental = query(
            "SELECT rental_id FROM rentals WHERE student_id = %s AND status IN ('active', 'overdue')",
            (res["student_id"],), fetch="one"
        )
        if existing_rental:
            flash(f"Cannot issue: Student already has an active or overdue rental (#{existing_rental['rental_id']}). Please process its return first.", "error")
            return redirect(url_for("admin_rentals"))

        due_at = datetime.now() + timedelta(days=2)
        execute("UPDATE reservations SET status = 'completed' WHERE reservation_id = %s", (reservation_id,))
        execute(
            """INSERT INTO rentals (student_id, bicycle_id, issued_at, due_at, status, issued_by)
               VALUES (%s, %s, NOW(), %s, 'active', %s)""",
            (res["student_id"], res["bicycle_id"], due_at, session.get("staff_name", "Staff"))
        )
        execute("UPDATE bicycles SET status = 'rented' WHERE bicycle_id = %s", (res["bicycle_id"],))
        flash(f"Reservation #{reservation_id} issued as active rental (Due in 2 days). ✅", "success")
    else:
        flash("Reservation not found or cannot be issued.", "error")
    return redirect(url_for("admin_rentals"))


@app.route("/admin/reservations/cancel/<int:reservation_id>", methods=["POST"])
@admin_required
def cancel_reservation_admin(reservation_id):
    """Admin: cancel a reservation and make bicycle available again."""
    res = query("SELECT * FROM reservations WHERE reservation_id = %s", (reservation_id,), fetch="one")
    if res and res["status"] in ("pending", "confirmed"):
        execute("UPDATE reservations SET status = 'cancelled' WHERE reservation_id = %s", (reservation_id,))
        execute(
            "UPDATE bicycles SET status = 'available' WHERE bicycle_id = %s AND status = 'reserved'",
            (res["bicycle_id"],)
        )
        flash(f"Reservation #{reservation_id} cancelled. Bicycle returned to available pool.", "success")
    else:
        flash("Reservation not found or already closed.", "error")
    return redirect(url_for("admin_rentals"))


# ─────────────────────────────────────────────────────────────
# BACKGROUND JOB: Mark overdue rentals (call via cron or periodic task)
# ─────────────────────────────────────────────────────────────

@app.route("/admin/sync-overdue", methods=["POST"])
@admin_required
def sync_overdue():
    """Mark active rentals past their due date as overdue."""
    count = execute(
        "UPDATE rentals SET status='overdue' WHERE status='active' AND due_at < NOW()"
    )
    # Also expire old pending reservations
    execute(
        "UPDATE reservations SET status='cancelled' WHERE status IN ('pending','confirmed') AND expires_at < NOW()"
    )
    # Free bikes from expired reservations
    execute(
        """UPDATE bicycles SET status='available'
           WHERE status='reserved'
           AND bicycle_id NOT IN (
               SELECT bicycle_id FROM reservations WHERE status IN ('pending','confirmed')
           )"""
    )
    flash("Overdue sync complete.", "success")
    return redirect(url_for("admin_dashboard"))


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
