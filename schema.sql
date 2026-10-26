-- ============================================================
-- Bicycle Rental Management System - Database Schema
-- Database: bicycle_rental_db
-- ============================================================

CREATE DATABASE IF NOT EXISTS bicycle_rental_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE bicycle_rental_db;

-- ------------------------------------------------------------
-- Table: stations
-- Represents physical docking/rental stations on campus
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stations (
    station_id   INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    location     VARCHAR(200) NOT NULL,
    capacity     INT          NOT NULL DEFAULT 10,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- Table: bicycles
-- Individual bicycles linked to a home station
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bicycles (
    bicycle_id   INT AUTO_INCREMENT PRIMARY KEY,
    station_id   INT          NOT NULL,
    model        VARCHAR(100) NOT NULL DEFAULT 'Standard',
    type         ENUM('standard','electric','mountain') NOT NULL DEFAULT 'standard',
    status       ENUM('available','rented','maintenance','reserved') NOT NULL DEFAULT 'available',
    added_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (station_id) REFERENCES stations(station_id) ON DELETE CASCADE
);

-- ------------------------------------------------------------
-- Table: students
-- Campus students who can rent bicycles
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS students (
    student_id    INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(150) NOT NULL,
    email         VARCHAR(150) NOT NULL UNIQUE,
    phone         VARCHAR(20),
    roll_number   VARCHAR(30)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL DEFAULT '',
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS staff (
    staff_id      INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(150) NOT NULL,
    email         VARCHAR(150) NOT NULL UNIQUE,
    phone         VARCHAR(20)  DEFAULT NULL,
    role          ENUM('admin','staff','manager') NOT NULL DEFAULT 'staff',
    password_hash VARCHAR(255) NOT NULL DEFAULT '',
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- Table: rentals
-- Records of bicycle rentals (issued & returned)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rentals (
    rental_id    INT AUTO_INCREMENT PRIMARY KEY,
    student_id   INT          NOT NULL,
    bicycle_id   INT          NOT NULL,
    staff_id     INT          DEFAULT NULL,
    issued_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    due_at       DATETIME     NOT NULL,
    returned_at  DATETIME     DEFAULT NULL,
    status       ENUM('active','returned','overdue') NOT NULL DEFAULT 'active',
    issued_by    VARCHAR(100) DEFAULT 'Staff',
    fine_amount  DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    fine_paid    TINYINT(1)   NOT NULL DEFAULT 0,
    fine_paid_at DATETIME     DEFAULT NULL,
    late_days    INT          NOT NULL DEFAULT 0,
    FOREIGN KEY (student_id)  REFERENCES students(student_id)  ON DELETE CASCADE,
    FOREIGN KEY (bicycle_id)  REFERENCES bicycles(bicycle_id)  ON DELETE CASCADE,
    FOREIGN KEY (staff_id)    REFERENCES staff(staff_id)       ON DELETE SET NULL
);

-- ------------------------------------------------------------
-- Table: reservations
-- Student reservations before physical pickup
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id INT AUTO_INCREMENT PRIMARY KEY,
    student_id     INT          NOT NULL,
    bicycle_id     INT          NOT NULL,
    station_id     INT          NOT NULL,
    reserved_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at     DATETIME     NOT NULL,
    status         ENUM('pending','confirmed','cancelled','completed') NOT NULL DEFAULT 'pending',
    FOREIGN KEY (student_id)  REFERENCES students(student_id)  ON DELETE CASCADE,
    FOREIGN KEY (bicycle_id)  REFERENCES bicycles(bicycle_id)  ON DELETE CASCADE,
    FOREIGN KEY (station_id)  REFERENCES stations(station_id)  ON DELETE CASCADE
);

-- ------------------------------------------------------------
-- Table: notifications
-- Alerts and communications to students
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    notification_id   INT AUTO_INCREMENT PRIMARY KEY,
    student_id        INT          NOT NULL,
    rental_id         INT          DEFAULT NULL,
    title             VARCHAR(150) NOT NULL DEFAULT 'Notification',
    message           TEXT         NOT NULL,
    notification_type VARCHAR(50)  NOT NULL DEFAULT 'info',
    status            VARCHAR(30)  NOT NULL DEFAULT 'unread',
    created_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
    FOREIGN KEY (rental_id)  REFERENCES rentals(rental_id)   ON DELETE SET NULL
);

-- ------------------------------------------------------------
-- High-Performance Indexes for Instant Queries
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_bicycles_status ON bicycles (status);
CREATE INDEX IF NOT EXISTS idx_bicycles_station_status ON bicycles (station_id, status);
CREATE INDEX IF NOT EXISTS idx_rentals_status_due ON rentals (status, due_at);
CREATE INDEX IF NOT EXISTS idx_rentals_student_status ON rentals (student_id, status);
CREATE INDEX IF NOT EXISTS idx_rentals_staff_id ON rentals (staff_id);
CREATE INDEX IF NOT EXISTS idx_reservations_status_expires ON reservations (status, expires_at);
CREATE INDEX IF NOT EXISTS idx_reservations_student_status ON reservations (student_id, status);
CREATE INDEX IF NOT EXISTS idx_notifications_student_status ON notifications (student_id, status);

-- ============================================================
-- SAMPLE DATA
-- (none — add real data through the admin portal)
-- ============================================================

-- Default admin account
--   Email:    admin@campuscycle.edu
--   Password: Admin@123  (hashed with werkzeug scrypt)
INSERT INTO staff (name, email, phone, role, password_hash)
VALUES (
    'System Administrator',
    'admin@campuscycle.edu',
    '9000000000',
    'admin',
    'scrypt:32768:8:1$hvx9jGzGfE6VJhL4$2dc57e64ac3e8210cb60dc59867313fff464d1f14c44e5da07068163f1213247c33468184c6b5c61155fa569816e720833d737b566ef2db818082c388e69a056'
) ON DUPLICATE KEY UPDATE name = name;
