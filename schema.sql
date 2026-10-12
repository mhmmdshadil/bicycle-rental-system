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
    student_id   INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(150) NOT NULL,
    email        VARCHAR(150) NOT NULL UNIQUE,
    phone        VARCHAR(20),
    roll_number  VARCHAR(30)  NOT NULL UNIQUE,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

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

-- ============================================================
-- SAMPLE DATA
-- ============================================================

INSERT INTO stations (name, location, capacity) VALUES
    ('Main Gate Station',       'Near Main Entrance, Block A',     12),
    ('Library Hub',             'In Front of Central Library',     8),
    ('Sports Complex Dock',     'East Wing, Sports Complex',       10),
    ('Hostel Block Station',    'Between Hostel C & D',            6),
    ('Tech Park Terminal',      'Innovation & Tech Park Entrance', 10);

INSERT INTO bicycles (station_id, model, type, status) VALUES
    (1, 'CityRide Pro',     'standard',  'available'),
    (1, 'CityRide Pro',     'standard',  'available'),
    (1, 'EcoGlide E1',      'electric',  'available'),
    (1, 'TrailBlazer X',    'mountain',  'rented'),
    (1, 'CityRide Pro',     'standard',  'maintenance'),
    (2, 'CityRide Pro',     'standard',  'available'),
    (2, 'EcoGlide E1',      'electric',  'available'),
    (2, 'CityRide Pro',     'standard',  'reserved'),
    (3, 'TrailBlazer X',    'mountain',  'available'),
    (3, 'CityRide Pro',     'standard',  'available'),
    (3, 'EcoGlide E1',      'electric',  'rented'),
    (4, 'CityRide Pro',     'standard',  'available'),
    (4, 'TrailBlazer X',    'mountain',  'available'),
    (5, 'CityRide Pro',     'standard',  'available'),
    (5, 'EcoGlide E1',      'electric',  'available'),
    (5, 'CityRide Pro',     'standard',  'rented');

INSERT INTO students (name, email, phone, roll_number) VALUES
    ('Arjun Mehta',     'arjun.mehta@campus.edu',   '9876543210', 'CS2021001'),
    ('Priya Sharma',    'priya.sharma@campus.edu',  '9876543211', 'EC2022045'),
    ('Rahul Nair',      'rahul.nair@campus.edu',    '9876543212', 'ME2021033'),
    ('Sneha Pillai',    'sneha.pillai@campus.edu',  '9876543213', 'CE2023012'),
    ('Aditya Rao',      'aditya.rao@campus.edu',    '9876543214', 'CS2022078');

INSERT INTO rentals (student_id, bicycle_id, issued_at, due_at, returned_at, status, issued_by) VALUES
    (1, 4,  NOW() - INTERVAL 2 DAY,  NOW() + INTERVAL 1 DAY,  NULL,                   'active',   'Staff A'),
    (2, 11, NOW() - INTERVAL 1 DAY,  NOW() + INTERVAL 2 DAY,  NULL,                   'active',   'Staff B'),
    (3, 16, NOW() - INTERVAL 3 DAY,  NOW() - INTERVAL 1 DAY,  NULL,                   'overdue',  'Staff A'),
    (4, 6,  NOW() - INTERVAL 5 DAY,  NOW() - INTERVAL 3 DAY,  NOW() - INTERVAL 3 DAY, 'returned', 'Staff C'),
    (5, 9,  NOW() - INTERVAL 1 DAY,  NOW() + INTERVAL 3 DAY,  NULL,                   'active',   'Staff B');

INSERT INTO reservations (student_id, bicycle_id, station_id, reserved_at, expires_at, status) VALUES
    (1, 8, 2, NOW() - INTERVAL 30 MINUTE, NOW() + INTERVAL 30 MINUTE, 'pending'),
    (2, 3, 1, NOW() - INTERVAL 1 HOUR,    NOW() + INTERVAL 2 HOUR,    'confirmed'),
    (3, 7, 2, NOW() - INTERVAL 2 HOUR,    NOW() - INTERVAL 1 HOUR,    'cancelled');
