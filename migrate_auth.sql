-- ============================================================
-- Auth Migration for bicycle_rental_db
-- Run this ONCE to add auth columns and create the admin account
-- ============================================================

USE bicycle_rental_db;

-- 1. Add password_hash to students table
ALTER TABLE students
  ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255) NOT NULL DEFAULT '' AFTER roll_number;

-- 2. Ensure staff table has password_hash (not plain password)
-- If staff table already exists and has a 'password' column, rename it
-- The CREATE TABLE IF NOT EXISTS in schema.sql already uses 'password' - we migrate:
ALTER TABLE staff
  CHANGE COLUMN IF EXISTS `password` `password_hash` VARCHAR(255) NOT NULL DEFAULT '';

-- 3. Insert the default admin account
--    Email: admin@campuscycle.edu
--    Password: Admin@123
--    (hash generated with werkzeug scrypt)
INSERT INTO staff (name, email, phone, role, password_hash)
VALUES (
  'System Administrator',
  'admin@campuscycle.edu',
  '9000000000',
  'admin',
  'scrypt:32768:8:1$hvx9jGzGfE6VJhL4$2dc57e64ac3e8210cb60dc59867313fff464d1f14c44e5da07068163f1213247c33468184c6b5c61155fa569816e720833d737b566ef2db818082c388e69a056'
)
ON DUPLICATE KEY UPDATE name = name;
