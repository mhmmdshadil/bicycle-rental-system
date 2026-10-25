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
    staff_id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL,
    phone VARCHAR(20) DEFAULT NULL,
    role ENUM('admin', 'staff', 'manager') NOT NULL DEFAULT 'staff',
    password VARCHAR(255) NOT NULL DEFAULT 'staff123',
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (staff_id),
    UNIQUE KEY email (email)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
-- ------------------------------------------------------------
-- Table: rentals
-- Records of bicycle rentals (issued & returned)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rentals (
    rental_id    INT AUTO_INCREMENT PRIMARY KEY,
    student_id   INT          NOT NULL,
    bicycle_id   INT          NOT NULL,
    issued_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    due_at       DATETIME     NOT NULL,
    returned_at  DATETIME     DEFAULT NULL,
    status       ENUM('active','returned','overdue') NOT NULL DEFAULT 'active',
    issued_by    VARCHAR(100) DEFAULT 'Staff',
    FOREIGN KEY (student_id)  REFERENCES students(student_id)  ON DELETE CASCADE,
    FOREIGN KEY (bicycle_id)  REFERENCES bicycles(bicycle_id)  ON DELETE CASCADE
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
CREATE TABLE IF NOT EXISTS notifications (
    notification_id INT NOT NULL AUTO_INCREMENT,
    rental_id INT NOT NULL,
    student_id INT NOT NULL,
    message TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    notification_type VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    status VARCHAR(30) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'unread',
    PRIMARY KEY (notification_id),
    KEY fk_notifications_rental (rental_id),
    KEY fk_notifications_student (student_id),
    CONSTRAINT fk_notifications_rental
        FOREIGN KEY (rental_id)
        REFERENCES rentals (rental_id),
    CONSTRAINT fk_notifications_student
        FOREIGN KEY (student_id)
        REFERENCES students (student_id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Table: staff
-- Admin and staff accounts for the management portal
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staff (
    staff_id      INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(150) NOT NULL,
    email         VARCHAR(150) NOT NULL UNIQUE,
    phone         VARCHAR(20)  DEFAULT NULL,
    role          ENUM('admin','staff','manager') NOT NULL DEFAULT 'staff',
    password_hash VARCHAR(255) NOT NULL DEFAULT '',
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

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
