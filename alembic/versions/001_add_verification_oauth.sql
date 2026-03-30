"""Add is_verified and google_id to users table

Run this on the VPS to add the new columns:
  docker exec -i emotionflow-postgres psql -U emotionflow emotionflow < alembic/versions/001_add_verification_oauth.sql
"""

-- Add email verification flag (default false for existing users)
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT false;

-- Add Google OAuth ID
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE;
CREATE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id);
