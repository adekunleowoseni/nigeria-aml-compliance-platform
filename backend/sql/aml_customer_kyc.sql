-- Customer KYC persisted for STR Word generation (created automatically on API startup).
CREATE TABLE IF NOT EXISTS aml_customer_kyc (
    customer_id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    account_number TEXT NOT NULL,
    account_opened DATE NOT NULL,
    customer_address TEXT NOT NULL,
    line_of_business TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    date_of_birth DATE NOT NULL,
    id_number TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
