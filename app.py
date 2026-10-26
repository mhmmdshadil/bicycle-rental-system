"""
app.py - Bicycle Rental Management System
Flask backend with full authentication, session management, and route protection.
"""

import os
import time
import threading
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, has_request_context
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
import mysql.connector
from mysql.connector import Error, pooling
from datetime import datetime, timedelta
import re

# ─────────────────────────────────────────
# App Initialisation
# ─────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "bicycle_rental_secret_key"

# ─────────────────────────────────────────
# Database Configuration & Connection Pool
# ─────────────────────────────────────────
DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "user":     os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "Shadil@12"),
    "database": os.environ.get("DB_NAME", "bicycle_rental_db"),
    "port":     int(os.environ.get("DB_PORT", 3306)),
    "charset":  "utf8mb4",
}

db_pool = None
try:
    _pool_cfg = dict(DB_CONFIG)
    if os.environ.get("DB_SSL", "").lower() in ("true", "1", "yes"):
        _pool_cfg["ssl_disabled"] = False
        _pool_cfg["ssl_verify_cert"] = False
        _pool_cfg["ssl_verify_identity"] = False
    db_pool = pooling.MySQLConnectionPool(
        pool_name="campuscycle_pool",
        pool_size=10,
        pool_reset_session=True,
        **_pool_cfg
    )
    print("[DB POOL] Initialized connection pool (size=10).")
except Exception as _e:
    print(f"[DB POOL WARNING] {_e}. Falling back to standard connections.")
    db_pool = None


def get_db_connection():
    """
    Return a MySQL connection.
    If inside a Flask request, reuse the connection cached on `flask.g`
    to eliminate redundant TCP/SSL handshakes.
    """
    if has_request_context():
        if hasattr(g, "_db_conn") and g._db_conn is not None:
            try:
                if g._db_conn.is_connected():
                    return g._db_conn
            except Exception:
                g._db_conn = None

    conn = None
    if db_pool:
        try:
            conn = db_pool.get_connection()
        except Exception as e:
            conn = None

    if conn is None:
        try:
            config = dict(DB_CONFIG)
            if os.environ.get("DB_SSL", "").lower() in ("true", "1", "yes"):
                config["ssl_disabled"] = False
                config["ssl_verify_cert"] = False
                config["ssl_verify_identity"] = False
            conn = mysql.connector.connect(**config)
        except Error as e:
            print(f"[DB ERROR] {e}")
            return None

    if has_request_context():
        g._db_conn = conn
    return conn


@app.teardown_appcontext
def teardown_db(exception=None):
    """Clean up request-scoped database connection at the end of each request."""
    conn = getattr(g, "_db_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


@app.after_request
def add_performance_headers(response):
    """Cache static assets aggressively and add performance/security headers."""
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = "no-cache, private"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def query(sql, params=None, fetch="all"):
    """
    Utility: run a SELECT query and return rows.
    Reuses request-scoped connection; closes cursor immediately.
    """
    conn = get_db_connection()
    if conn is None:
        return [] if fetch == "all" else None
    cursor = None
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
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if not has_request_context() and conn:
            try:
                conn.close()
            except Exception:
                pass


def execute(sql, params=None):
    """Utility: run INSERT / UPDATE / DELETE queries. Returns last insert ID or False."""
    conn = get_db_connection()
    if conn is None:
        return False
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()
        return cursor.lastrowid or True
    except Error as e:
        print(f"[EXECUTE ERROR] {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if not has_request_context() and conn:
            try:
                conn.close()
            except Exception:
                pass


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

_last_sync_time = 0
_sync_lock = threading.Lock()

def auto_sync_status(force=False):
    """
    Automatically synchronize fleet status:
    1. Expire pending reservations past their 2-hour window and restore the bicycles to 'available'.
    2. Mark active rentals past their due date as 'overdue' and send alert notifications.
    Debounced: runs at most once every 120 seconds unless force=True.
    """
    global _last_sync_time
    now_ts = time.time()
    if not force and (now_ts - _last_sync_time < 120):
        return

    with _sync_lock:
        if not force and (time.time() - _last_sync_time < 120):
            return
        _last_sync_time = time.time()

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

            # 2. Overdue rentals alert - single batch insert rather than loop of queries
            execute("""
                INSERT INTO notifications (student_id, rental_id, title, message, notification_type, status)
                SELECT r.student_id, r.rental_id, 'Rental Overdue ⚠️',
                       CONCAT('Your rental for \'', b.model, '\' is overdue. Please return it to any station as soon as possible.'),
                       'alert', 'unread'
                FROM rentals r
                JOIN bicycles b ON r.bicycle_id = b.bicycle_id
                WHERE r.status = 'active' AND r.due_at < NOW()
                  AND NOT EXISTS (
                      SELECT 1 FROM notifications n
                      WHERE n.rental_id = r.rental_id AND n.notification_type = 'alert'
                  )
            """)

            overdue_rows = query(
                """
                SELECT rental_id, student_id, due_at, bicycle_id
                FROM rentals
                WHERE status IN ('active', 'overdue') AND due_at < NOW()
                ORDER BY due_at ASC
                """
            ) or []
            for rental in overdue_rows:
                due_at = rental.get("due_at")
                if not due_at:
                    continue
                fine_amount, late_days = calculate_overdue_fine(due_at, datetime.now())
                execute(
                    """
                    UPDATE rentals
                    SET status = 'overdue',
                        late_days = %s,
                        fine_amount = %s,
                        fine_paid = CASE WHEN fine_paid = 1 THEN 1 ELSE 0 END
                    WHERE rental_id = %s
                    """,
                    (late_days, fine_amount, rental["rental_id"]),
                )
                if fine_amount > 0:
                    create_notification(
                        rental["student_id"],
                        "Late Return Fine Updated 💳",
                        f"Your rental is overdue. Current outstanding fine: ₹{fine_amount:.2f}. Please settle it with campus administration.",
                        "warning",
                        rental_id=rental["rental_id"],
                    )

            execute("""
                UPDATE rentals
                SET status = 'active'
                WHERE status = 'overdue' AND due_at >= NOW()
            """)
        except Exception as e:
            print(f"[AUTO-SYNC] {e}")


def ensure_indexes():
    """Ensure database indexes exist for blazing performance."""
    indexes = [
        ("idx_bicycles_status", "bicycles", "(status)"),
        ("idx_bicycles_station_status", "bicycles", "(station_id, status)"),
        ("idx_rentals_status_due", "rentals", "(status, due_at)"),
        ("idx_rentals_student_status", "rentals", "(student_id, status)"),
        ("idx_reservations_status_expires", "reservations", "(status, expires_at)"),
        ("idx_reservations_student_status", "reservations", "(student_id, status)"),
        ("idx_notifications_student_status", "notifications", "(student_id, status)"),
    ]
    for idx_name, table, cols in indexes:
        try:
            execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} {cols}")
        except Exception:
            pass


def ensure_database_columns():
    """Ensure fine-tracking columns exist for overdue rentals in MySQL-compatible syntax."""
    existing = query(
        "SHOW COLUMNS FROM rentals LIKE 'fine_amount'",
        fetch="one",
    )
    if not existing:
        execute("ALTER TABLE rentals ADD COLUMN fine_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00")

    existing = query(
        "SHOW COLUMNS FROM rentals LIKE 'fine_paid'",
        fetch="one",
    )
    if not existing:
        execute("ALTER TABLE rentals ADD COLUMN fine_paid TINYINT(1) NOT NULL DEFAULT 0")

    existing = query(
        "SHOW COLUMNS FROM rentals LIKE 'fine_paid_at'",
        fetch="one",
    )
    if not existing:
        execute("ALTER TABLE rentals ADD COLUMN fine_paid_at DATETIME NULL")

    existing = query(
        "SHOW COLUMNS FROM rentals LIKE 'late_days'",
        fetch="one",
    )
    if not existing:
        execute("ALTER TABLE rentals ADD COLUMN late_days INT NOT NULL DEFAULT 0")


ensure_database_columns()


def get_homepage_stats():
    """Return the live station, bicycle, and bike-type totals for the landing page."""
    stats = query(
        """
        SELECT
            (SELECT COUNT(*) FROM stations) AS total_stations,
            (SELECT COUNT(*) FROM bicycles) AS total_bikes,
            (SELECT COUNT(*) FROM bicycles WHERE status = 'available') AS available_bikes,
            (SELECT COUNT(DISTINCT type) FROM bicycles) AS total_types
        """,
        fetch="one",
    ) or {}

    return {
        "stations": int(stats.get("total_stations") or 0),
        "bicycles": int(stats.get("total_bikes") or 0),
        "types": int(stats.get("total_types") or 0),
        "available": int(stats.get("available_bikes") or 0),
    }


def assign_display_ids(items, display_key):
    """Assign a sequential display ID based on current-order list without modifying the DB PKs."""
    ordered_items = list(items or [])
    for index, item in enumerate(ordered_items, start=1):
        item[display_key] = index
    return ordered_items


def assign_student_display_ids(students):
    """Add a sequential display ID that matches the registered-student order, independent of DB PK gaps."""
    return assign_display_ids(students, "display_student_id")


def calculate_overdue_fine(due_at, now=None):
    """Calculate the current fine for an overdue rental using a daily rate."""
    now = now or datetime.now()
    if not due_at:
        return 0.0, 0
    if due_at <= now:
        delta = now - due_at
        overdue_days = max(1, int(delta.total_seconds() // 86400) + 1)
        return round(overdue_days * 25.0, 2), overdue_days
    return 0.0, 0


# ─────────────────────────────────────────────────────────────
# HERO / LANDING PAGE
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Hero landing page with live fleet statistics."""
    return render_template("index.html", stats=get_homepage_stats())


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

    unpaid_fine = query(
        "SELECT COALESCE(SUM(fine_amount), 0) AS total FROM rentals WHERE student_id = %s AND fine_paid = 0 AND status IN ('active', 'overdue')",
        (student_id,), fetch="one",
    )
    if unpaid_fine and float(unpaid_fine.get("total") or 0) > 0:
        flash(f"You have an outstanding offline fine of ₹{float(unpaid_fine['total']):.2f}. Please settle it with campus administration before reserving another bicycle.", "error")
        return redirect(url_for("student_notifications"))

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

    rentals = assign_display_ids(
        query(
            """SELECT r.rental_id, r.issued_at, r.due_at, r.returned_at, r.status, r.issued_by,
                      r.fine_amount, r.fine_paid, r.late_days,
                      b.bicycle_id, b.model, b.type,
                      s.name AS station_name
               FROM rentals r
               JOIN bicycles b ON r.bicycle_id = b.bicycle_id
               JOIN stations s ON b.station_id = s.station_id
               WHERE r.student_id = %s
               ORDER BY r.issued_at DESC""",
            (student_id,),
        ) or [],
        "display_rental_id",
    )

    reservations = assign_display_ids(
        query(
            """SELECT res.reservation_id, res.reserved_at, res.expires_at, res.status,
                      b.bicycle_id, b.model, b.type,
                      s.name AS station_name
               FROM reservations res
               JOIN bicycles b ON res.bicycle_id = b.bicycle_id
               JOIN stations s ON res.station_id = s.station_id
               WHERE res.student_id = %s
               ORDER BY res.reserved_at DESC""",
            (student_id,),
        ) or [],
        "display_reservation_id",
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


@app.route("/student/notifications/delete/<int:notification_id>", methods=["POST"])
@student_required
def delete_notification(notification_id):
    """Delete a read notification for the current student (only allowed if status='read')."""
    student_id = session["student_id"]
    notif = query(
        "SELECT status FROM notifications WHERE notification_id = %s AND student_id = %s",
        (notification_id, student_id), fetch="one"
    )
    if not notif:
        flash("Notification not found.", "error")
        return redirect(url_for("student_notifications"))
    if notif["status"] != "read":
        flash("Please mark the notification as read before deleting it.", "error")
        return redirect(url_for("student_notifications"))
    execute(
        "DELETE FROM notifications WHERE notification_id = %s AND student_id = %s AND status = 'read'",
        (notification_id, student_id)
    )
    flash("Notification removed.", "success")
    return redirect(url_for("student_notifications"))


@app.route("/student/notifications/delete-all-read", methods=["POST"])
@student_required
def delete_all_read_notifications():
    """Delete all read notifications for the current student."""
    student_id = session["student_id"]
    execute(
        "DELETE FROM notifications WHERE student_id = %s AND status = 'read'",
        (student_id,)
    )
    flash("All read notifications have been cleared.", "success")
    return redirect(url_for("student_notifications"))


# ─────────────────────────────────────────────────────────────
# ADMIN PANEL  (all routes session-protected)
# ─────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_dashboard():
    """Admin Dashboard – KPI cards, staff team, student directory, notifications, and recent activity."""
    auto_sync_status()
    kpis = query("""
        SELECT
            (SELECT COUNT(*) FROM stations) AS total_stations,
            (SELECT COUNT(*) FROM bicycles) AS total_bikes,
            (SELECT COUNT(*) FROM bicycles WHERE status='available') AS available_bikes,
            (SELECT COUNT(*) FROM rentals WHERE status='active') AS active_rentals,
            (SELECT COUNT(*) FROM rentals WHERE status='overdue') AS overdue_rentals,
            (SELECT COUNT(*) FROM students) AS total_students,
            (SELECT COUNT(*) FROM staff) AS total_staff,
            (SELECT COUNT(*) FROM notifications) AS total_notifications,
            (SELECT COUNT(*) FROM reservations WHERE status IN ('pending', 'confirmed')) AS pending_reservations
    """, fetch="one") or {}

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

    students_list = assign_student_display_ids(
        query(
            """SELECT s.student_id, s.name, s.email, s.phone, s.roll_number, s.created_at,
                      (SELECT COUNT(*) FROM rentals r WHERE r.student_id = s.student_id AND r.status IN ('active', 'overdue')) AS active_rentals_cnt,
                      (SELECT COUNT(*) FROM reservations res WHERE res.student_id = s.student_id AND res.status IN ('pending', 'confirmed')) AS active_res_cnt
               FROM students s
               ORDER BY s.created_at DESC"""
        ) or []
    )

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
        total_stations       = kpis.get("total_stations") or 0,
        total_bikes          = kpis.get("total_bikes") or 0,
        available_bikes      = kpis.get("available_bikes") or 0,
        active_rentals       = kpis.get("active_rentals") or 0,
        overdue_rentals      = kpis.get("overdue_rentals") or 0,
        total_students       = kpis.get("total_students") or 0,
        total_staff          = kpis.get("total_staff") or 0,
        total_notifications  = kpis.get("total_notifications") or 0,
        pending_reservations = kpis.get("pending_reservations") or 0,
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
    bikes = assign_display_ids(
        query(
            """SELECT b.bicycle_id, b.station_id, b.model, b.type, b.status, b.added_at,
                      s.name AS station_name
               FROM bicycles b
               JOIN stations s ON b.station_id = s.station_id
               ORDER BY b.added_at ASC, b.bicycle_id ASC"""
        ) or [],
        "display_bicycle_id",
    )
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


@app.route("/admin/fines")
@admin_required
def admin_fines():
    """Admin: Dedicated fine management – list all fines, filter by paid/unpaid, mark paid."""
    auto_sync_status()
    paid_filter = request.args.get("paid", "all")  # all | unpaid | paid

    base_sql = """
        SELECT r.rental_id, r.student_id, r.issued_at, r.due_at, r.returned_at,
               r.status, r.fine_amount, r.fine_paid, r.fine_paid_at, r.late_days,
               st.name AS student_name, st.roll_number, st.email,
               b.model, b.type,
               s.name AS station_name
        FROM rentals r
        JOIN students st ON r.student_id = st.student_id
        JOIN bicycles  b  ON r.bicycle_id  = b.bicycle_id
        JOIN stations  s  ON b.station_id  = s.station_id
        WHERE r.fine_amount > 0
    """
    if paid_filter == "unpaid":
        fines = query(base_sql + " AND r.fine_paid = 0 ORDER BY r.due_at ASC") or []
    elif paid_filter == "paid":
        fines = query(base_sql + " AND r.fine_paid = 1 ORDER BY r.fine_paid_at DESC") or []
    else:
        fines = query(base_sql + " ORDER BY r.fine_paid ASC, r.due_at ASC") or []

    # Summary stats
    summary = query("""
        SELECT
            COUNT(*) AS total_fines,
            SUM(CASE WHEN fine_paid = 0 THEN fine_amount ELSE 0 END) AS total_unpaid,
            SUM(CASE WHEN fine_paid = 1 THEN fine_amount ELSE 0 END) AS total_collected,
            COUNT(CASE WHEN fine_paid = 0 THEN 1 END) AS unpaid_count,
            COUNT(CASE WHEN fine_paid = 1 THEN 1 END) AS paid_count
        FROM rentals
        WHERE fine_amount > 0
    """, fetch="one") or {}

    now = datetime.now()
    return render_template(
        "admin_fines.html",
        fines=fines,
        paid_filter=paid_filter,
        summary=summary,
        now=now,
    )


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
               r.fine_amount, r.fine_paid, r.late_days,
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
               0.00 AS fine_amount, 0 AS fine_paid, 0 AS late_days,
               st.name AS student_name, st.roll_number, st.email,
               b.bicycle_id, b.model, b.type,
               s.name AS station_name
        FROM reservations res
        JOIN students st ON res.student_id = st.student_id
        JOIN bicycles b  ON res.bicycle_id  = b.bicycle_id
        JOIN stations s  ON res.station_id  = s.station_id
    """

    if status_filter == "reserved":
        records = assign_display_ids(query(res_base + " ORDER BY res.reserved_at DESC") or [], "display_reservation_id")
    elif status_filter in ("active", "overdue", "returned"):
        records = assign_display_ids(query(rentals_base + " WHERE r.status = %s ORDER BY r.issued_at DESC", (status_filter,)) or [], "display_rental_id")
    else:
        rentals_all      = query(rentals_base) or []
        reservations_all = query(res_base) or []
        records = rentals_all + reservations_all
        records.sort(key=lambda x: x["issued_at"] or datetime.min, reverse=True)
        records = assign_display_ids(records, "display_record_id")

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
        if rental.get("fine_amount") and rental.get("fine_paid") != 1:
            flash(
                f"Outstanding fine of ₹{float(rental.get('fine_amount') or 0):.2f} must be marked paid before this rental can be fully closed.",
                "warning",
            )
            return redirect(url_for("admin_rentals"))
        execute(
            "UPDATE rentals SET status='returned', returned_at=NOW(), fine_paid=CASE WHEN fine_paid IS NULL THEN 0 ELSE fine_paid END WHERE rental_id=%s",
            (rental_id,),
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


@app.route("/admin/rentals/fine/pay/<int:rental_id>", methods=["POST"])
@admin_required
def mark_rental_fine_paid(rental_id):
    """Admin: mark an overdue rental's offline fine as paid."""
    rental = query("SELECT * FROM rentals WHERE rental_id = %s", (rental_id,), fetch="one")
    if not rental:
        flash("Rental not found.", "error")
        return redirect(url_for("admin_rentals"))

    ok = execute(
        "UPDATE rentals SET fine_paid = 1, fine_paid_at = NOW() WHERE rental_id = %s",
        (rental_id,),
    )
    if ok:
        create_notification(
            rental["student_id"],
            "Fine Payment Recorded ✅",
            f"Your offline fine for rental #{rental_id} has been marked as paid by campus administration.",
            "success",
            rental_id=rental_id,
        )
        flash(f"Fine for Rental #{rental_id} marked as paid. ✅", "success")
    else:
        flash("Unable to update fine payment status.", "error")
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
        unpaid_fine = query(
            "SELECT COALESCE(SUM(fine_amount), 0) AS total FROM rentals WHERE student_id = %s AND fine_paid = 0 AND status IN ('active', 'overdue')",
            (res["student_id"],), fetch="one",
        )
        if unpaid_fine and float(unpaid_fine.get("total") or 0) > 0:
            flash(
                f"Cannot issue bike: Student has an outstanding offline fine of ₹{float(unpaid_fine['total']):.2f}. Mark it paid before issuing a new bike.",
                "error",
            )
            return redirect(url_for("admin_rentals"))

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
    auto_sync_status(force=True)
    flash("Fleet synchronization and overdue check complete. ✅", "success")
    return redirect(url_for("admin_dashboard"))


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ensure_indexes()
    app.run(debug=True, port=5000)
