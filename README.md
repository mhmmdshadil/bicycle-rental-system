# 🚲 CampusCycle – Bicycle Rental Management System

A minimalist, full-stack campus bicycle rental web application built with **Python (Flask)**, **MySQL**, **HTML5**, and clean **Vanilla CSS**.

---

## 🎨 Design System & Aesthetic

Inspired by soft minimal UI design with warm cream/beige tones:
- **Background Color**: `#fcf8f5` (soft warm cream)
- **Cards & Containers**: `#ffffff` (pure white) with `border-radius: 16px` and soft, subtle ambient shadows
- **Primary Action Buttons**: Warm terracotta/orange (`#d97743`) with smooth hover transition (`#c46535`)
- **Secondary Buttons**: Clean outline styling
- **Typography**: Clean, modern sans-serif (*Inter* via Google Fonts), spacious layouts, and focused single-task pages

---

## 🏗️ Architecture & Page Flow

No authentication required for frictionless navigation:

### 1. Landing / Hero (`/`)
- **Template**: `templates/index.html`
- Minimalist centered welcome screen featuring a floating bicycle icon, campus statistics, and direct entry points to the **Student Portal** and **Admin Panel**.

### 2. Student Portal Flow
- **Dashboard (`/student`)** (`templates/student_dashboard.html`):
  - Overview cards displaying bikes available right now, student's active rentals, and pending reservations.
  - Interactive student profile switcher for demonstration.
- **Browse Bicycles & Stations (`/student/bikes`)** (`templates/student_bikes.html`):
  - Station occupancy progress bars (capacity vs. available docks).
  - Filter bicycles by type: *Standard*, *Electric*, or *Mountain*.
  - Instant one-click bicycle reservation.
- **My Rentals & Notifications (`/student/notifications`)** (`templates/student_notifications.html`):
  - Active and historical rental logs.
  - Due date alerts and overdue warnings.
  - Status tracking for bicycle reservations.
  - Self-service reservation cancellation: students can cancel their own active reservation with one click, immediately releasing the bicycle back to available.

### 3. Admin Panel Flow
- **Admin Dashboard (`/admin`)** (`templates/admin_dashboard.html`):
  - High-level KPIs: Total Stations, Fleet Size, Available Bikes, Active Rentals, Overdue Rentals, and Registered Students.
  - Recent checkout and return transaction log.
- **Manage Stations & Bikes (`/admin/stations`)** (`templates/admin_stations.html`):
  - Per-station docking occupancy and status distribution.
  - Full bicycle fleet inventory with instant status updater (*available*, *rented*, *maintenance*, *reserved*).
- **Rental Records (`/admin/rentals`)** (`templates/admin_rentals.html`):
  - Complete issue and return records handled by staff.
  - Filter tabs by status (*All*, *Active*, *Overdue*, *Returned*).
  - One-click **"Mark Returned"** action that updates the rental record and automatically marks the bicycle as available.

---

## 🗄️ Database Schema (`bicycle_rental_db`)

The relational MySQL schema is defined in [schema.sql](file:///c:/Users/Admin/Desktop/bicycle-project/bicycle-rental-system/schema.sql):

- **`stations`**: Docking stations across campus (`station_id`, `name`, `location`, `capacity`).
- **`bicycles`**: Bikes docked at stations (`bicycle_id`, `station_id`, `model`, `type`, `status`).
- **`students`**: Student records (`student_id`, `name`, `email`, `phone`, `roll_number`).
- **`rentals`**: Checkouts and check-ins (`rental_id`, `student_id`, `bicycle_id`, `staff_id`, `issued_at`, `due_at`, `returned_at`, `status`, `issued_by`, fines).
- **`reservations`**: Pre-pickup hold requests (`reservation_id`, `student_id`, `bicycle_id`, `station_id`, `reserved_at`, `expires_at`, `status`).

Includes pre-seeded realistic sample data for 5 stations, 16 bicycles, 5 students, and sample rental records.

---

## 🚀 Setup & Installation Instructions

### 1. Prerequisites
- Python 3.8+
- MySQL Server (via XAMPP, WAMP, Docker, or MySQL Community Server)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Import Database Schema
Using MySQL CLI:
```bash
mysql -u root -p < schema.sql
```
*Or open phpMyAdmin / MySQL Workbench, create or import `schema.sql` directly.*

### 4. Configure Database Connection
Edit the `DB_CONFIG` dictionary in [app.py](file:///c:/Users/Admin/Desktop/bicycle-project/bicycle-rental-system/app.py) if your MySQL port, username, or password differs:
```python
DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",          # Your MySQL username
    "password": "",              # Your MySQL password
    "database": "bicycle_rental_db",
    "charset":  "utf8mb4",
}
```

### 5. Start the Application
```bash
python app.py
```
Open your browser and navigate to:
```
http://127.0.0.1:5000/
```

---

## 📁 Project Structure

```
bicycle-rental-system/
├── app.py                     # Flask application with all routes and MySQL queries
├── schema.sql                 # MySQL schema with tables & sample campus seed data
├── requirements.txt           # Python package requirements
├── README.md                  # System documentation and setup guide
├── static/
│   └── css/
│       └── style.css          # Design system stylesheet (warm cream aesthetic)
└── templates/
    ├── index.html             # Hero welcome page
    ├── student_dashboard.html # Student portal overview
    ├── student_bikes.html     # Real-time bicycle & station browser
    ├── student_notifications.html # Student rentals & due date notices
    ├── admin_dashboard.html   # Admin fleet KPI metrics
    ├── admin_stations.html    # Station capacity & bicycle maintenance
    └── admin_rentals.html     # Rental circulation records & return handler
```