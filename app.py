"""
app.py - Bicycle Rental Management System
Flask backend connecting to MySQL database (bicycle_rental_db).
Routes cover: Hero, Student Portal (dashboard, bikes, notifications),
              Admin Panel (dashboard, stations, rentals).
"""

from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta

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
    "user":     "root",          # Change to your MySQL username
    "password": "Shadil@12",              # Change to your MySQL password
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
    """Utility: run INSERT / UPDATE / DELETE queries."""
    conn = get_db_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()
        return True
    except Error as e:
        print(f"[EXECUTE ERROR] {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


# ─────────────────────────────────────────────────────────────
# HERO / LANDING PAGE
# ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    """Hero landing page with Student Portal and Admin Panel links."""
    return render_template("index.html")


# ─────────────────────────────────────────────────────────────
# STUDENT PORTAL
# ─────────────────────────────────────────────────────────────

@app.route("/student")
def student_dashboard():
    """
    Student Dashboard – summary cards:
    available bikes, active rentals, pending reservations.
    Default student_id=1 for demo (no auth).
    """
    student_id = request.args.get("student_id", 1, type=int)

    # Fetch current student
    student = query(
        "SELECT * FROM students WHERE student_id = %s", (student_id,), fetch="one"
    )

    # Count available bicycles
    available_count = query(
        "SELECT COUNT(*) AS cnt FROM bicycles WHERE status = 'available'",
        fetch="one",
    )

    # Count active rentals for this student
    active_rentals = query(
        "SELECT COUNT(*) AS cnt FROM rentals WHERE student_id = %s AND status = 'active'",
        (student_id,), fetch="one",
    )

    # Count pending/confirmed reservations for this student
    pending_reservations = query(
        "SELECT COUNT(*) AS cnt FROM reservations WHERE student_id = %s AND status IN ('pending','confirmed')",
        (student_id,), fetch="one",
    )

    # All students list for switcher
    students = query("SELECT student_id, name, roll_number FROM students ORDER BY name")

    return render_template(
        "student_dashboard.html",
        student=student,
        students=students,
        available_count=available_count["cnt"] if available_count else 0,
        active_rentals=active_rentals["cnt"] if active_rentals else 0,
        pending_reservations=pending_reservations["cnt"] if pending_reservations else 0,
        student_id=student_id,
    )


@app.route("/student/bikes")
def student_bikes():
    """
    Browse Bicycles & Stations – real-time availability grouped by station.
    Students can trigger a reservation from here.
    """
    student_id = request.args.get("student_id", 1, type=int)
    type_filter = request.args.get("type", "all")

    # Build bicycle query with optional type filter
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

    # Stations summary (capacity vs available)
    stations = query(
        """SELECT s.station_id, s.name, s.location, s.capacity,
                  SUM(CASE WHEN b.status = 'available' THEN 1 ELSE 0 END) AS available,
                  COUNT(b.bicycle_id) AS total
           FROM stations s
           LEFT JOIN bicycles b ON s.station_id = b.station_id
           GROUP BY s.station_id
           ORDER BY s.name"""
    )

    return render_template(
        "student_bikes.html",
        bikes=bikes,
        stations=stations,
        type_filter=type_filter,
        student_id=student_id,
    )


@app.route("/student/reserve/<int:bicycle_id>", methods=["POST"])
def reserve_bicycle(bicycle_id):
    """Create a reservation for a bicycle (expires in 2 hours)."""
    student_id = request.form.get("student_id", 1, type=int)
    station_id = request.form.get("station_id", type=int)
    expires_at = datetime.now() + timedelta(hours=2)

    # Check bike is still available
    bike = query(
        "SELECT * FROM bicycles WHERE bicycle_id = %s AND status = 'available'",
        (bicycle_id,), fetch="one",
    )
    if not bike:
        flash("Bicycle is no longer available.", "error")
        return redirect(url_for("student_bikes", student_id=student_id))

    # Insert reservation
    ok = execute(
        """INSERT INTO reservations (student_id, bicycle_id, station_id, expires_at, status)
           VALUES (%s, %s, %s, %s, 'pending')""",
        (student_id, bicycle_id, station_id, expires_at),
    )
    if ok:
        # Mark bike as reserved
        execute(
            "UPDATE bicycles SET status = 'reserved' WHERE bicycle_id = %s",
            (bicycle_id,),
        )
        flash("Reservation placed successfully! Pick up within 2 hours.", "success")
    else:
        flash("Reservation failed. Please try again.", "error")

    return redirect(url_for("student_notifications", student_id=student_id))


@app.route("/student/unreserve/<int:reservation_id>", methods=["POST"])
def unreserve_bicycle(reservation_id):
    """Cancel/unreserve a reservation and return the bicycle to available status."""
    student_id = request.form.get("student_id", type=int)
    if not student_id:
        student_id = request.args.get("student_id", 1, type=int)

    reservation = query(
        "SELECT * FROM reservations WHERE reservation_id = %s",
        (reservation_id,),
        fetch="one",
    )

    if not reservation:
        flash("Reservation not found.", "error")
        return redirect(url_for("student_notifications", student_id=student_id))

    if reservation["status"] not in ("pending", "confirmed"):
        flash("This reservation is no longer active and cannot be unreserved.", "error")
        return redirect(url_for("student_notifications", student_id=student_id))

    # Mark reservation as cancelled
    ok = execute(
        "UPDATE reservations SET status = 'cancelled' WHERE reservation_id = %s",
        (reservation_id,),
    )
    if ok:
        # Restore bicycle status to available
        execute(
            "UPDATE bicycles SET status = 'available' WHERE bicycle_id = %s AND status = 'reserved'",
            (reservation["bicycle_id"],),
        )
        flash("Reservation cancelled successfully! Bicycle has been unreserved.", "success")
    else:
        flash("Failed to unreserve the bicycle. Please try again.", "error")

    return redirect(url_for("student_notifications", student_id=student_id))


@app.route("/student/notifications")
def student_notifications():
    """
    My Rentals & Notifications – active rentals, overdue alerts,
    and reservation status for the current student.
    """
    student_id = request.args.get("student_id", 1, type=int)

    student = query(
        "SELECT * FROM students WHERE student_id = %s", (student_id,), fetch="one"
    )

    # Active & overdue rentals
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

    # Reservations
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

    # All students for switcher
    students = query("SELECT student_id, name, roll_number FROM students ORDER BY name")

    now = datetime.now()
    return render_template(
        "student_notifications.html",
        student=student,
        students=students,
        rentals=rentals,
        reservations=reservations,
        now=now,
        student_id=student_id,
    )


# ─────────────────────────────────────────────────────────────
# ADMIN PANEL
# ─────────────────────────────────────────────────────────────

@app.route("/admin")
def admin_dashboard():
    """
    Admin Dashboard – high-level KPI cards:
    total stations, total bikes, active rentals, overdue count.
    """
    total_stations = query("SELECT COUNT(*) AS cnt FROM stations", fetch="one")
    total_bikes    = query("SELECT COUNT(*) AS cnt FROM bicycles", fetch="one")
    available_bikes= query("SELECT COUNT(*) AS cnt FROM bicycles WHERE status='available'", fetch="one")
    active_rentals = query("SELECT COUNT(*) AS cnt FROM rentals WHERE status='active'", fetch="one")
    overdue_rentals= query("SELECT COUNT(*) AS cnt FROM rentals WHERE status='overdue'", fetch="one")
    total_students = query("SELECT COUNT(*) AS cnt FROM students", fetch="one")

    pending_reservations = query(
        "SELECT COUNT(*) AS cnt FROM reservations WHERE status IN ('pending', 'confirmed')",
        fetch="one",
    )

    # Recent activity (rentals + reservations)
    recent_rentals_list = query(
        """SELECT r.rental_id, 'rental' AS record_type, r.issued_at, r.status,
                  st.name AS student_name, st.roll_number,
                  b.model, b.type
           FROM rentals r
           JOIN students st ON r.student_id = st.student_id
           JOIN bicycles b  ON r.bicycle_id  = b.bicycle_id"""
    )
    recent_res_list = query(
        """SELECT res.reservation_id AS rental_id, 'reservation' AS record_type,
                  res.reserved_at AS issued_at, res.status,
                  st.name AS student_name, st.roll_number,
                  b.model, b.type
           FROM reservations res
           JOIN students st ON res.student_id = st.student_id
           JOIN bicycles b  ON res.bicycle_id  = b.bicycle_id"""
    )
    recent_activity = (recent_rentals_list or []) + (recent_res_list or [])
    recent_activity.sort(key=lambda x: x["issued_at"] or datetime.min, reverse=True)
    recent_rentals = recent_activity[:6]

    return render_template(
        "admin_dashboard.html",
        total_stations       = total_stations["cnt"]       if total_stations       else 0,
        total_bikes          = total_bikes["cnt"]          if total_bikes          else 0,
        available_bikes      = available_bikes["cnt"]      if available_bikes      else 0,
        active_rentals       = active_rentals["cnt"]       if active_rentals       else 0,
        overdue_rentals      = overdue_rentals["cnt"]      if overdue_rentals      else 0,
        total_students       = total_students["cnt"]       if total_students       else 0,
        pending_reservations = pending_reservations["cnt"] if pending_reservations else 0,
        recent_rentals       = recent_rentals,
    )


@app.route("/admin/stations")
def admin_stations():
    """
    Manage Stations & Bikes – per-station capacity and bicycle status breakdown.
    """
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

    # All bicycles with their station
    bikes = query(
        """SELECT b.bicycle_id, b.model, b.type, b.status, b.added_at,
                  s.name AS station_name
           FROM bicycles b
           JOIN stations s ON b.station_id = s.station_id
           ORDER BY s.name, b.status"""
    )

    return render_template("admin_stations.html", stations=stations, bikes=bikes)


@app.route("/admin/stations/update-status", methods=["POST"])
def update_bike_status():
    """Admin: quickly change a bicycle's status from the station view."""
    bicycle_id = request.form.get("bicycle_id", type=int)
    new_status  = request.form.get("status")
    allowed     = {"available", "rented", "maintenance", "reserved"}
    if new_status in allowed:
        execute(
            "UPDATE bicycles SET status = %s WHERE bicycle_id = %s",
            (new_status, bicycle_id),
        )
        flash(f"Bicycle #{bicycle_id} status updated to '{new_status}'.", "success")
    else:
        flash("Invalid status value.", "error")
    return redirect(url_for("admin_stations"))


@app.route("/admin/rentals")
def admin_rentals():
    """
    Rental Records – full list with student, bicycle, station details.
    Includes active/past rentals as well as bicycle reservations.
    Filterable by status ('all', 'active', 'reserved', 'overdue', 'returned').
    """
    status_filter = request.args.get("status", "all")

    rentals_base = """
        SELECT r.rental_id AS record_id, r.rental_id, 'rental' AS record_type,
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
        SELECT res.reservation_id AS record_id, res.reservation_id, 'reservation' AS record_type,
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
        rentals_all = query(rentals_base) or []
        reservations_all = query(res_base) or []
        records = rentals_all + reservations_all
        records.sort(key=lambda x: x["issued_at"] or datetime.min, reverse=True)

    # Active reservations count for filter badge
    res_count = query(
        "SELECT COUNT(*) AS cnt FROM reservations WHERE status IN ('pending', 'confirmed')",
        fetch="one",
    )
    reserved_count = res_count["cnt"] if res_count else 0

    return render_template(
        "admin_rentals.html",
        rentals=records,
        status_filter=status_filter,
        reserved_count=reserved_count,
    )


@app.route("/admin/rentals/return/<int:rental_id>", methods=["POST"])
def return_rental(rental_id):
    """Admin: mark a rental as returned and free the bicycle."""
    rental = query(
        "SELECT * FROM rentals WHERE rental_id = %s", (rental_id,), fetch="one"
    )
    if rental and rental["status"] in ("active", "overdue"):
        execute(
            "UPDATE rentals SET status='returned', returned_at=NOW() WHERE rental_id=%s",
            (rental_id,),
        )
        execute(
            "UPDATE bicycles SET status='available' WHERE bicycle_id=%s",
            (rental["bicycle_id"],),
        )
        flash(f"Rental #{rental_id} marked as returned.", "success")
    else:
        flash("Rental not found or already returned.", "error")
    return redirect(url_for("admin_rentals"))


@app.route("/admin/reservations/issue/<int:reservation_id>", methods=["POST"])
def issue_reservation(reservation_id):
    """Admin: issue a reserved bicycle to student (converts reservation into active rental)."""
    res = query(
        "SELECT * FROM reservations WHERE reservation_id = %s",
        (reservation_id,),
        fetch="one",
    )
    if res and res["status"] in ("pending", "confirmed"):
        due_at = datetime.now() + timedelta(days=2)
        # Mark reservation completed
        execute(
            "UPDATE reservations SET status = 'completed' WHERE reservation_id = %s",
            (reservation_id,),
        )
        # Create active rental record in rentals table
        execute(
            """INSERT INTO rentals (student_id, bicycle_id, issued_at, due_at, status, issued_by)
               VALUES (%s, %s, NOW(), %s, 'active', 'Staff')""",
            (res["student_id"], res["bicycle_id"], due_at),
        )
        # Mark bicycle as rented
        execute(
            "UPDATE bicycles SET status = 'rented' WHERE bicycle_id = %s",
            (res["bicycle_id"],),
        )
        flash(f"Reservation #{reservation_id} issued successfully as an active rental.", "success")
    else:
        flash("Reservation not found or cannot be issued.", "error")
    return redirect(url_for("admin_rentals"))


@app.route("/admin/reservations/cancel/<int:reservation_id>", methods=["POST"])
def cancel_reservation_admin(reservation_id):
    """Admin: cancel a reservation and make bicycle available again."""
    res = query(
        "SELECT * FROM reservations WHERE reservation_id = %s",
        (reservation_id,),
        fetch="one",
    )
    if res and res["status"] in ("pending", "confirmed"):
        execute(
            "UPDATE reservations SET status = 'cancelled' WHERE reservation_id = %s",
            (reservation_id,),
        )
        execute(
            "UPDATE bicycles SET status = 'available' WHERE bicycle_id = %s AND status = 'reserved'",
            (res["bicycle_id"],),
        )
        flash(f"Reservation #{reservation_id} cancelled. Bicycle returned to available.", "success")
    else:
        flash("Reservation not found or already closed.", "error")
    return redirect(url_for("admin_rentals"))


# ─────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
