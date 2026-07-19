"""Add is_verified and google_id to users table

Run this on the VPS to add the new columns:
  docker exec -i emotionflow-postgres psql -U emotionflow emotionflow < alembic/versions/001_add_verification_oauth.sql
"""

-- Add email verification flag (default false for existing users)
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT false;

-- Mark constrained demo accounts without affecting existing users
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_test_account BOOLEAN NOT NULL DEFAULT false;

-- Add Google OAuth ID
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE;
CREATE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id);

-- Billing ledger compatibility for databases created before compute-unit accounting
ALTER TABLE billing_events ADD COLUMN IF NOT EXISTS compute_units INTEGER NOT NULL DEFAULT 0;

-- Older billing ledgers required a USD cost supplied by the application.
-- Compute-unit accounting leaves that legacy field at a neutral default.
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'billing_events' AND column_name = 'cost_usd'
    ) THEN
        ALTER TABLE billing_events ALTER COLUMN cost_usd SET DEFAULT 0.0;
    END IF;
END $$;
