-- Feature Engineering View (AI-ready)
-- This is where Postgres becomes the "skeleton" and ML gets the "muscle".
-- You can refresh this view into a materialized view for training/inference batches.

-- Example schema assumption:
--   transactions(id, customer_id, amount, currency, transaction_type, channel, timestamp, counterparty_id, status, metadata jsonb)
--   customers(id, segment, occupation, kyc_level, risk_rating, created_at, geo_risk)

CREATE OR REPLACE VIEW fe_transaction_features AS
SELECT
  t.id                         AS transaction_id,
  t.customer_id,
  t.amount,
  t.currency,
  t.transaction_type,
  t.channel,
  t.timestamp,
  -- velocity features
  COUNT(*) OVER (
    PARTITION BY t.customer_id
    ORDER BY t.timestamp
    RANGE BETWEEN INTERVAL '2 hours' PRECEDING AND CURRENT ROW
  )                            AS tx_count_2h,
  SUM(t.amount) OVER (
    PARTITION BY t.customer_id
    ORDER BY t.timestamp
    RANGE BETWEEN INTERVAL '2 hours' PRECEDING AND CURRENT ROW
  )                            AS tx_amount_sum_2h,
  -- fan-in approximation: distinct counterparties in 2 hours
  COUNT(DISTINCT t.counterparty_id) OVER (
    PARTITION BY t.customer_id
    ORDER BY t.timestamp
    RANGE BETWEEN INTERVAL '2 hours' PRECEDING AND CURRENT ROW
  )                            AS distinct_counterparties_2h,
  -- profile features (join as available)
  c.segment                    AS customer_segment,
  c.occupation                 AS occupation,
  c.kyc_level                  AS kyc_level,
  c.risk_rating                AS risk_rating,
  c.geo_risk                   AS geo_risk
FROM transactions t
LEFT JOIN customers c ON c.id = t.customer_id;

