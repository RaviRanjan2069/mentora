-- Runs once on first start of the postgres container.
CREATE EXTENSION IF NOT EXISTS vector;

-- Separate database for the dev Moodle (docker compose --profile lms).
CREATE DATABASE moodle;
