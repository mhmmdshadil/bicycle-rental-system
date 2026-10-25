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
    "host":     os.environ.get("DB_HOST", "localhost"),
    "user":     os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "Shadil@12"),
    "database": os.environ.get("DB_NAME", "bicycle_rental_db"),
    "port":     int(os.environ.get("DB_PORT", 3306)),
    "charset":  "utf8mb4",
}


def get_db_connection():
    """Return a fresh MySQL connection, or None on failure."""
    try:
        config = dict(DB_CONFIG)
        if os.environ.get("DB_SSL", "").lower() in ("true", "1", "yes"):
            config["ssl_disabled"] = False
            config["ssl_verify_cert"] = False
            config["ssl_verify_identity"] = False
        conn = mysql.connector.connect(**config)
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

def create_notification(student_id, title, message, notification_type="info", rental_id=None):
    """Safely insert a notification for a student."""
    try:
        execute(
            """INSERT INTO notifications (student_id, rental_id, title, message, notification_type, status)
               VALUES (%s, %s, %s, %s, %s, 'unread')""",
            (student_id, rental_id, title, message, notification_type)
        )
    except Exception as e:
        print(f"[NOTIFICATION ERROR] {e}")

def auto_sync_status():
    """
    Automatically synchronize fleet status:
    1. Expire pending reservations past their 2-hour window and restore the bicycles to 'available'.
    2. Mark active rentals past their due date as 'overdue' and send alert notifications.
    """
    try:
        # 1. Expire stale reservations
        expired_res = query("""
            SELECT res.reservation_id, res.student_id, b.model
            FROM reservations res
            JOIN bicycles b ON res.bicycle_id = b.bicycle_id
            WHERE res.status IN ('pending', 'confirmed') AND res.expires_at < NOW()
        """)
        for r in expired_res or []:
            create_notification(
                r["student_id"],
                "Reservation Expired",
                f"Your 2-hour hold on '{r['model']}' has expired and the bicycle has been released.",
                "warning"
            )

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

        # 2. Overdue rentals alert
        overdue_rentals = query("""
            SELECT r.rental_id, r.student_id, b.model
            FROM rentals r
            JOIN bicycles b ON r.bicycle_id = b.bicycle_id
            WHERE r.status = 'active' AND r.due_at < NOW()
        """)
        for ov in overdue_rentals or []:
            existing_alert = query(
                "SELECT notification_id FROM notifications WHERE rental_id = %s AND notification_type = 'alert'",
                (ov["rental_id"],), fetch="one"
            )
            if not existing_alert:
                create_notification(
                    ov["student_id"],
                    "Rental Overdue ⚠️",
                    f"Your rental for '{ov['model']}' is overdue. Please return it to any station as soon as possible.",
                    "alert",
                    rental_id=ov["rental_id"]
                )

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

    unread_notifs = query(
        "SELECT COUNT(*) AS cnt FROM notifications WHERE student_id = %s AND status = 'unread'",
        (student_id,), fetch="one"
    )

    return render_template(
        "student_dashboard.html",
        student=student,
        available_count=available_count["cnt"] if available_count else 0,
        active_rentals=active_rentals["cnt"] if active_rentals else 0,
        overdue_rentals=overdue_rentals["cnt"] if overdue_rentals else 0,
        pending_reservations=pending_reservations["cnt"] if pending_reservations else 0,
        unread_notifications=unread_notifs["cnt"] if unread_notifs else 0,
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

    create_notification(
        student_id,
        "Reservation Confirmed 🎉",
        f"You have reserved {bike['model']} (Bike #{bicycle_id}). Please pick it up at the docking station within 2 hours.",
        "info"
    )
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
        create_notification(
            student_id,
            "Reservation Cancelled",
            f"Your reservation #{reservation_id} has been cancelled. Bicycle #{reservation['bicycle_id']} is now available for others.",
            "warning"
        )
        flash("Reservation cancelled. Bicycle is now available again.", "success")
    else:
        flash("Failed to cancel reservation. Please try again.", "error")

    return redirect(url_for("student_notifications"))

@app.route("/student/reservation/cancel/<int:reservation_id>", methods=["POST"])
@student_required
def cancel_reservation(reservation_id):
    """Alias for student reservation cancellation."""
    return unreserve_bicycle(reservation_id)


@app.route("/student/notifications")
@student_required
def student_notifications():
    """My Rentals, Reservations & System Notifications."""
    auto_sync_status()
    student_id = session["student_id"]

    student = query("SELECT * FROM students WHERE student_id = %s", (student_id,), fetch="one")

    notifications = query(
        """SELECT * FROM notifications
           WHERE student_id = %s
           ORDER BY created_at DESC""",
        (student_id,),
    ) or []

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

    unread_count = sum(1 for n in notifications if n.get("status") == "unread")
    now = datetime.now()

    return render_template(
        "student_notifications.html",
        student=student,
        notifications=notifications,
        unread_count=unread_count,
        rentals=rentals,
        reservations=reservations,
        now=now,
    )


@app.route("/student/notifications/read/<int:notification_id>", methods=["POST"])
@student_required
def mark_notification_read(notification_id):
    """Mark a single notification as read."""
    student_id = session["student_id"]
    execute(
        "UPDATE notifications SET status = 'read' WHERE notification_id = %s AND student_id = %s",
        (notification_id, student_id)
    )
    flash("Notification marked as read.", "success")
    return redirect(url_for("student_notifications"))


@app.route("/student/notifications/read-all", methods=["POST"])
@student_required
def mark_all_notifications_read():
    """Mark all notifications as read for current student."""
    student_id = session["student_id"]
    execute("UPDATE notifications SET status = 'read' WHERE student_id = %s", (student_id,))
    flash("All notifications marked as read.", "success")
    return redirect(url_for("student_notifications"))


# ─────────────────────────────────────────────────────────────
# ADMIN PANEL  (all routes session-protected)
# ─────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_dashboard():
    """Admin Dashboard – KPI cards, staff team, student directory, notifications, and recent activity."""
    auto_sync_status()
    total_stations   = query("SELECT COUNT(*) AS cnt FROM stations", fetch="one")
    total_bikes      = query("SELECT COUNT(*) AS cnt FROM bicycles", fetch="one")
    available_bikes  = query("SELECT COUNT(*) AS cnt FROM bicycles WHERE status='available'", fetch="one")
    active_rentals   = query("SELECT COUNT(*) AS cnt FROM rentals WHERE status='active'", fetch="one")
    overdue_rentals  = query("SELECT COUNT(*) AS cnt FROM rentals WHERE status='overdue'", fetch="one")
    total_students   = query("SELECT COUNT(*) AS cnt FROM students", fetch="one")
    total_staff      = query("SELECT COUNT(*) AS cnt FROM staff", fetch="one")
    total_notifs     = query("SELECT COUNT(*) AS cnt FROM notifications", fetch="one")
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

    staff_members = query(
        "SELECT staff_id, name, email, phone, role, created_at FROM staff ORDER BY FIELD(role, 'admin', 'manager', 'staff'), name"
    ) or []

    students_list = query(
        """SELECT s.student_id, s.name, s.email, s.phone, s.roll_number, s.created_at,
                  (SELECT COUNT(*) FROM rentals r WHERE r.student_id = s.student_id AND r.status IN ('active', 'overdue')) AS active_rentals_cnt,
                  (SELECT COUNT(*) FROM reservations res WHERE res.student_id = s.student_id AND res.status IN ('pending', 'confirmed')) AS active_res_cnt
           FROM students s
           ORDER BY s.created_at DESC"""
    ) or []

    notifications_list = query(
        """SELECT n.notification_id, n.student_id, n.title, n.message, n.notification_type, n.status, n.created_at,
                  s.name AS student_name, s.roll_number
           FROM notifications n
           JOIN students s ON n.student_id = s.student_id
           ORDER BY n.created_at DESC LIMIT 30"""
    ) or []

    stations_list = query("SELECT station_id, name, capacity FROM stations ORDER BY name") or []

    return render_template(
        "admin_dashboard.html",
        total_stations       = total_stations["cnt"]  if total_stations  else 0,
        total_bikes          = total_bikes["cnt"]      if total_bikes     else 0,
        available_bikes      = available_bikes["cnt"]  if available_bikes else 0,
        active_rentals       = active_rentals["cnt"]   if active_rentals  else 0,
        overdue_rentals      = overdue_rentals["cnt"]  if overdue_rentals else 0,
        total_students       = total_students["cnt"]   if total_students  else 0,
        total_staff          = total_staff["cnt"]      if total_staff     else 0,
        total_notifications  = total_notifs["cnt"]     if total_notifs    else 0,
        pending_reservations = pending_res["cnt"]      if pending_res     else 0,
        recent_rentals       = recent_activity[:8],
        staff_members        = staff_members,
        students_list        = students_list,
        notifications_list   = notifications_list,
        stations_list        = stations_list,
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
    ) or []
    bikes = query(
        """SELECT b.bicycle_id, b.station_id, b.model, b.type, b.status, b.added_at,
                  s.name AS station_name
           FROM bicycles b
           JOIN stations s ON b.station_id = s.station_id
           ORDER BY s.name, b.status, b.bicycle_id"""
    ) or []
    return render_template("admin_stations.html", stations=stations, bikes=bikes)


@app.route("/admin/stations/add", methods=["POST"])
@admin_required
def add_station():
    """Admin: Add a new docking station."""
    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    capacity = request.form.get("capacity", type=int)

    if not name or not location or not capacity or capacity < 1:
        flash("Please provide a valid station name, location, and capacity (minimum 1).", "error")
        return redirect(url_for("admin_stations"))

    ok = execute(
        "INSERT INTO stations (name, location, capacity) VALUES (%s, %s, %s)",
        (name, location, capacity)
    )
    if ok:
        flash(f"Docking Station '{name}' (Capacity: {capacity}) created successfully! 🚉", "success")
    else:
        flash("Failed to create station. Please try again.", "error")
    return redirect(url_for("admin_stations"))


@app.route("/admin/stations/edit", methods=["POST"])
@admin_required
def edit_station():
    """Admin: Edit an existing station's details and capacity."""
    station_id = request.form.get("station_id", type=int)
    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    capacity = request.form.get("capacity", type=int)

    if not station_id or not name or not location or not capacity or capacity < 1:
        flash("All fields are required and capacity must be at least 1.", "error")
        return redirect(url_for("admin_stations"))

    # Check current number of bikes at this station
    current_bikes = query(
        "SELECT COUNT(*) AS cnt FROM bicycles WHERE station_id = %s",
        (station_id,), fetch="one"
    )
    bike_cnt = current_bikes["cnt"] if current_bikes else 0
    if capacity < bike_cnt:
        flash(
            f"Cannot lower capacity to {capacity}: Station currently holds {bike_cnt} bicycles. Please reassign bikes before reducing capacity.",
            "error"
        )
        return redirect(url_for("admin_stations"))

    ok = execute(
        "UPDATE stations SET name = %s, location = %s, capacity = %s WHERE station_id = %s",
        (name, location, capacity, station_id)
    )
    if ok:
        flash(f"Station '{name}' updated successfully! ✅", "success")
    else:
        flash("Failed to update station.", "error")
    return redirect(url_for("admin_stations"))


@app.route("/admin/stations/delete/<int:station_id>", methods=["POST"])
@admin_required
def delete_station(station_id):
    """Admin: Delete a station if no bicycles are docked there."""
    bikes_at_station = query(
        "SELECT COUNT(*) AS cnt FROM bicycles WHERE station_id = %s",
        (station_id,), fetch="one"
    )
    if bikes_at_station and bikes_at_station["cnt"] > 0:
        flash(
            f"Cannot delete station: There are currently {bikes_at_station['cnt']} bicycle(s) assigned to it. Reassign or delete these bicycles first.",
            "error"
        )
        return redirect(url_for("admin_stations"))

    st = query("SELECT name FROM stations WHERE station_id = %s", (station_id,), fetch="one")
    st_name = st["name"] if st else f"#{station_id}"
    ok = execute("DELETE FROM stations WHERE station_id = %s", (station_id,))
    if ok:
        flash(f"Station '{st_name}' removed successfully.", "success")
    else:
        flash("Failed to delete station.", "error")
    return redirect(url_for("admin_stations"))


@app.route("/admin/bicycles/add", methods=["POST"])
@admin_required
def add_bicycle():
    """Admin: Add a new bicycle to a docking station."""
    station_id = request.form.get("station_id", type=int)
    model = request.form.get("model", "").strip() or "Standard Cruiser"
    bike_type = request.form.get("type", "standard").strip().lower()
    status = request.form.get("status", "available").strip().lower()

    if not station_id:
        flash("Please select a valid docking station.", "error")
        return redirect(url_for("admin_stations"))

    if bike_type not in ("standard", "electric", "mountain"):
        bike_type = "standard"
    if status not in ("available", "maintenance"):
        status = "available"

    # Validate station exists and check capacity limit
    station = query("SELECT name, capacity FROM stations WHERE station_id = %s", (station_id,), fetch="one")
    if not station:
        flash("Selected station does not exist.", "error")
        return redirect(url_for("admin_stations"))

    current_count = query("SELECT COUNT(*) AS cnt FROM bicycles WHERE station_id = %s", (station_id,), fetch="one")
    c_cnt = current_count["cnt"] if current_count else 0

    if c_cnt >= station["capacity"]:
        flash(
            f"Cannot add bicycle: Station '{station['name']}' has reached its full capacity ({c_cnt}/{station['capacity']}). Please select another station or expand capacity.",
            "error"
        )
        return redirect(url_for("admin_stations"))

    new_id = execute(
        "INSERT INTO bicycles (station_id, model, type, status) VALUES (%s, %s, %s, %s)",
        (station_id, model, bike_type, status)
    )
    if new_id:
        flash(f"Bicycle #{new_id} ({model} - {bike_type.capitalize()}) added to '{station['name']}'! 🚲", "success")
    else:
        flash("Failed to add bicycle. Please try again.", "error")
    return redirect(url_for("admin_stations"))


@app.route("/admin/bicycles/edit", methods=["POST"])
@admin_required
def edit_bicycle():
    """Admin: Edit bicycle model, type, station, and operational status."""
    bicycle_id = request.form.get("bicycle_id", type=int)
    station_id = request.form.get("station_id", type=int)
    model = request.form.get("model", "").strip()
    bike_type = request.form.get("type", "standard").strip().lower()
    status = request.form.get("status", "available").strip().lower()

    if not bicycle_id or not station_id or not model:
        flash("Missing required information for bicycle update.", "error")
        return redirect(url_for("admin_stations"))

    if bike_type not in ("standard", "electric", "mountain"):
        bike_type = "standard"

    # Safety: don't manually set to 'available' or change station if actively rented
    active_rental = query(
        "SELECT rental_id FROM rentals WHERE bicycle_id = %s AND status IN ('active', 'overdue')",
        (bicycle_id,), fetch="one"
    )
    if active_rental:
        flash(
            f"Cannot modify Bike #{bicycle_id}: It is currently checked out under Rental #{active_rental['rental_id']}. Please process the return first.",
            "error"
        )
        return redirect(url_for("admin_stations"))

    # If status set to maintenance, cancel any pending reservation
    if status == "maintenance":
        execute(
            "UPDATE reservations SET status='cancelled' WHERE bicycle_id=%s AND status IN ('pending','confirmed')",
            (bicycle_id,)
        )

    ok = execute(
        "UPDATE bicycles SET station_id = %s, model = %s, type = %s, status = %s WHERE bicycle_id = %s",
        (station_id, model, bike_type, status, bicycle_id)
    )
    if ok:
        flash(f"Bicycle #{bicycle_id} ({model}) updated successfully! ✅", "success")
    else:
        flash("Failed to update bicycle.", "error")
    return redirect(url_for("admin_stations"))


@app.route("/admin/bicycles/delete/<int:bicycle_id>", methods=["POST"])
@admin_required
def delete_bicycle(bicycle_id):
    """Admin: Safely delete a bicycle from the fleet."""
    active_rental = query(
        "SELECT rental_id FROM rentals WHERE bicycle_id = %s AND status IN ('active', 'overdue')",
        (bicycle_id,), fetch="one"
    )
    if active_rental:
        flash(
            f"Cannot delete Bike #{bicycle_id}: It is actively rented out in Rental #{active_rental['rental_id']}.",
            "error"
        )
        return redirect(url_for("admin_stations"))

    active_res = query(
        "SELECT reservation_id FROM reservations WHERE bicycle_id = %s AND status IN ('pending', 'confirmed')",
        (bicycle_id,), fetch="one"
    )
    if active_res:
        flash(
            f"Cannot delete Bike #{bicycle_id}: It is reserved under Reservation #{active_res['reservation_id']}. Please cancel the reservation first.",
            "error"
        )
        return redirect(url_for("admin_stations"))

    ok = execute("DELETE FROM bicycles WHERE bicycle_id = %s", (bicycle_id,))
    if ok:
        flash(f"Bicycle #{bicycle_id} removed from inventory.", "success")
    else:
        flash("Failed to delete bicycle.", "error")
    return redirect(url_for("admin_stations"))


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

    if new_status in ("available", "reserved"):
        active_rental = query(
            "SELECT rental_id FROM rentals WHERE bicycle_id = %s AND status IN ('active', 'overdue')",
            (bicycle_id,), fetch="one"
        )
        if active_rental:
            flash(
                f"Cannot set Bike #{bicycle_id} to '{new_status}': it is currently checked out under Rental #{active_rental['rental_id']}. Please process the return first.",
                "error"
            )
            return redirect(url_for("admin_stations"))

    if new_status in ("available", "maintenance"):
        execute(
            "UPDATE reservations SET status='cancelled' WHERE bicycle_id=%s AND status IN ('pending','confirmed')",
            (bicycle_id,)
        )

    execute("UPDATE bicycles SET status = %s WHERE bicycle_id = %s", (new_status, bicycle_id))
    flash(f"Bicycle #{bicycle_id} status updated to '{new_status}'.", "success")
    return redirect(url_for("admin_stations"))


@app.route("/admin/staff/add", methods=["POST"])
@admin_required
def add_staff():
    """Admin: Add a new staff member or administrator."""
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    role = request.form.get("role", "staff").strip().lower()
    password = request.form.get("password", "")

    if not name or not email or not password:
        flash("Name, email, and password are required.", "error")
        return redirect(url_for("admin_dashboard"))

    if not validate_email(email):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("admin_dashboard"))

    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("admin_dashboard"))

    if role not in ("admin", "staff", "manager"):
        role = "staff"

    existing = query("SELECT staff_id FROM staff WHERE email = %s", (email,), fetch="one")
    if existing:
        flash(f"A staff account with email '{email}' already exists.", "error")
        return redirect(url_for("admin_dashboard"))

    pw_hash = generate_password_hash(password)
    ok = execute(
        "INSERT INTO staff (name, email, phone, role, password_hash) VALUES (%s, %s, %s, %s, %s)",
        (name, email, phone or None, role, pw_hash)
    )
    if ok:
        flash(f"Staff member '{name}' ({role.capitalize()}) added successfully! 👤", "success")
    else:
        flash("Failed to add staff member.", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/staff/delete/<int:staff_id>", methods=["POST"])
@admin_required
def delete_staff(staff_id):
    """Admin: Remove a staff account with safety checks."""
    if staff_id == session.get("staff_id"):
        flash("Security Alert: You cannot delete your own active administrator account.", "error")
        return redirect(url_for("admin_dashboard"))

    st = query("SELECT role, name FROM staff WHERE staff_id = %s", (staff_id,), fetch="one")
    if not st:
        flash("Staff member not found.", "error")
        return redirect(url_for("admin_dashboard"))

    if st["role"] == "admin":
        admin_count = query("SELECT COUNT(*) AS cnt FROM staff WHERE role = 'admin'", fetch="one")
        if admin_count and admin_count["cnt"] <= 1:
            flash("Cannot delete the only remaining Administrator account.", "error")
            return redirect(url_for("admin_dashboard"))

    ok = execute("DELETE FROM staff WHERE staff_id = %s", (staff_id,))
    if ok:
        flash(f"Staff account for '{st['name']}' has been removed.", "success")
    else:
        flash("Failed to delete staff member.", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/students/delete/<int:student_id>", methods=["POST"])
@admin_required
def delete_student(student_id):
    """Admin: Remove a student account if no active bicycle checkouts exist."""
    active = query(
        "SELECT rental_id FROM rentals WHERE student_id = %s AND status IN ('active', 'overdue')",
        (student_id,), fetch="one"
    )
    if active:
        flash("Cannot delete student: Student currently holds an active or overdue bicycle rental.", "error")
        return redirect(url_for("admin_dashboard"))

    st = query("SELECT name FROM students WHERE student_id = %s", (student_id,), fetch="one")
    st_name = st["name"] if st else f"#{student_id}"

    ok = execute("DELETE FROM students WHERE student_id = %s", (student_id,))
    if ok:
        flash(f"Student account for '{st_name}' removed from the system.", "success")
    else:
        flash("Failed to delete student account.", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/notifications/send", methods=["POST"])
@admin_required
def send_notification():
    """Admin: Send a notification message to an individual student or broadcast to all."""
    recipient = request.form.get("recipient", "").strip()
    title = request.form.get("title", "").strip() or "Campus Announcement"
    message = request.form.get("message", "").strip()
    notif_type = request.form.get("type", "info").strip()

    if not message:
        flash("Notification message cannot be blank.", "error")
        return redirect(url_for("admin_dashboard"))

    if notif_type not in ("info", "alert", "warning", "success"):
        notif_type = "info"

    if recipient == "all":
        all_students = query("SELECT student_id FROM students") or []
        for s in all_students:
            create_notification(s["student_id"], title, message, notif_type)
        flash(f"Broadcast notification sent to all {len(all_students)} registered students! 📢", "success")
    else:
        try:
            student_id = int(recipient)
            student = query("SELECT name FROM students WHERE student_id = %s", (student_id,), fetch="one")
            if not student:
                flash("Recipient student not found.", "error")
                return redirect(url_for("admin_dashboard"))
            create_notification(student_id, title, message, notif_type)
            flash(f"Notification sent to {student['name']}! ✉️", "success")
        except ValueError:
            flash("Invalid student recipient selected.", "error")

    return redirect(url_for("admin_dashboard"))


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
    rental = query(
        """SELECT r.*, b.model FROM rentals r
           JOIN bicycles b ON r.bicycle_id = b.bicycle_id
           WHERE r.rental_id = %s""",
        (rental_id,), fetch="one"
    )
    if rental and rental["status"] in ("active", "overdue"):
        execute(
            "UPDATE rentals SET status='returned', returned_at=NOW() WHERE rental_id=%s", (rental_id,)
        )
        execute("UPDATE bicycles SET status='available' WHERE bicycle_id=%s", (rental["bicycle_id"],))
        create_notification(
            rental["student_id"],
            "Bicycle Return Confirmed ✅",
            f"Your rental #{rental_id} for '{rental['model']}' has been returned and checked in. Thank you!",
            "success",
            rental_id=rental_id
        )
        flash(f"Rental #{rental_id} marked as returned. Bicycle is now available. ✅", "success")
    else:
        flash("Rental not found or already returned.", "error")
    return redirect(url_for("admin_rentals"))


@app.route("/admin/reservations/issue/<int:reservation_id>", methods=["POST"])
@admin_required
def issue_reservation(reservation_id):
    """Admin: issue a reserved bicycle (converts reservation to active rental)."""
    auto_sync_status()
    res = query(
        """SELECT res.*, b.model FROM reservations res
           JOIN bicycles b ON res.bicycle_id = b.bicycle_id
           WHERE res.reservation_id = %s""",
        (reservation_id,), fetch="one"
    )
    if res and res["status"] in ("pending", "confirmed"):
        existing_rental = query(
            "SELECT rental_id FROM rentals WHERE student_id = %s AND status IN ('active', 'overdue')",
            (res["student_id"],), fetch="one"
        )
        if existing_rental:
            flash(
                f"Cannot issue: Student already has an active/overdue rental (#{existing_rental['rental_id']}). Process its return first.",
                "error"
            )
            return redirect(url_for("admin_rentals"))

        due_at = datetime.now() + timedelta(days=2)
        execute("UPDATE reservations SET status = 'completed' WHERE reservation_id = %s", (reservation_id,))
        new_rental_id = execute(
            """INSERT INTO rentals (student_id, bicycle_id, issued_at, due_at, status, issued_by)
               VALUES (%s, %s, NOW(), %s, 'active', %s)""",
            (res["student_id"], res["bicycle_id"], due_at, session.get("staff_name", "Staff"))
        )
        execute("UPDATE bicycles SET status = 'rented' WHERE bicycle_id = %s", (res["bicycle_id"],))
        create_notification(
            res["student_id"],
            "Bicycle Checked Out 🚲",
            f"Your bicycle '{res['model']}' (Bike #{res['bicycle_id']}) is ready and checked out. Return due by {due_at.strftime('%b %d, %Y %I:%M %p')}.",
            "success",
            rental_id=new_rental_id if isinstance(new_rental_id, int) else None
        )
        flash(f"Reservation #{reservation_id} issued as active rental (Due in 2 days). ✅", "success")
    else:
        flash("Reservation not found or cannot be issued.", "error")
    return redirect(url_for("admin_rentals"))


@app.route("/admin/reservations/cancel/<int:reservation_id>", methods=["POST"])
@admin_required
def cancel_reservation_admin(reservation_id):
    """Admin: cancel a reservation and make bicycle available again."""
    res = query(
        """SELECT res.*, b.model FROM reservations res
           JOIN bicycles b ON res.bicycle_id = b.bicycle_id
           WHERE res.reservation_id = %s""",
        (reservation_id,), fetch="one"
    )
    if res and res["status"] in ("pending", "confirmed"):
        execute("UPDATE reservations SET status = 'cancelled' WHERE reservation_id = %s", (reservation_id,))
        execute(
            "UPDATE bicycles SET status = 'available' WHERE bicycle_id = %s AND status = 'reserved'",
            (res["bicycle_id"],)
        )
        create_notification(
            res["student_id"],
            "Reservation Cancelled by Staff",
            f"Your reservation #{reservation_id} for '{res['model']}' was cancelled by administration.",
            "warning"
        )
        flash(f"Reservation #{reservation_id} cancelled. Bicycle returned to available pool.", "success")
    else:
        flash("Reservation not found or already closed.", "error")
    return redirect(url_for("admin_rentals"))


@app.route("/admin/sync-overdue", methods=["POST"])
@admin_required
def sync_overdue():
    """Mark active rentals past their due date as overdue."""
    auto_sync_status()
    flash("Fleet synchronization and overdue check complete. ✅", "success")
    return redirect(url_for("admin_dashboard"))


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
