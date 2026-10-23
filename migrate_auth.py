"""
migrate_auth.py - One-time migration to add auth columns and seed admin account.
Run: python migrate_auth.py
"""
import mysql.connector
from werkzeug.security import generate_password_hash

DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "Shadil@12",
    "database": "bicycle_rental_db",
    "charset":  "utf8mb4",
}

conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

# --- 1. students table: add password_hash if missing ---
try:
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='bicycle_rental_db' AND TABLE_NAME='students' AND COLUMN_NAME='password_hash'
    """)
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE students ADD COLUMN password_hash VARCHAR(255) NOT NULL DEFAULT ''")
        conn.commit()
        print("OK: Added students.password_hash")
    else:
        print("OK: students.password_hash already exists")
except Exception as e:
    print(f"FAIL students: {e}")

# --- 2. Create staff table if it does not exist ---
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            staff_id     INT NOT NULL AUTO_INCREMENT,
            name         VARCHAR(150) NOT NULL,
            email        VARCHAR(150) NOT NULL,
            phone        VARCHAR(20)  DEFAULT NULL,
            role         ENUM('admin','staff','manager') NOT NULL DEFAULT 'staff',
            password_hash VARCHAR(255) NOT NULL DEFAULT '',
            created_at   TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (staff_id),
            UNIQUE KEY email (email)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    conn.commit()
    print("OK: staff table ensured")
except Exception as e:
    print(f"SKIP staff create: {e}")

# Handle case where staff table exists but has 'password' not 'password_hash'
try:
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='bicycle_rental_db' AND TABLE_NAME='staff' AND COLUMN_NAME='password'
    """)
    if cursor.fetchone():
        cursor.execute("ALTER TABLE staff CHANGE COLUMN `password` `password_hash` VARCHAR(255) NOT NULL DEFAULT ''")
        conn.commit()
        print("OK: Renamed staff.password -> staff.password_hash")
except Exception as e:
    print(f"SKIP rename: {e}")

# --- 3. Seed admin account ---
admin_ph = generate_password_hash("Admin@123")
try:
    cursor.execute(
        """INSERT INTO staff (name, email, phone, role, password_hash)
           VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE password_hash = VALUES(password_hash)""",
        ("System Administrator", "admin@campuscycle.edu", "9000000000", "admin", admin_ph)
    )
    conn.commit()
    print("OK: Admin seeded -> admin@campuscycle.edu / Admin@123")
except Exception as e:
    print(f"FAIL admin: {e}")

cursor.close()
conn.close()
print("\nAll done!")
