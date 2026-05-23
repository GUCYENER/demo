BEGIN;

-- Create two test users (temporary, rolled back at end)
INSERT INTO users (id, full_name, username, email, phone, password, role_id, company_id)
VALUES (90042, 'RLS Test 42', 'rls_test_42', 'rls42@test.local', '0000000042', 'x', 2, 1)
ON CONFLICT (id) DO NOTHING;
INSERT INTO users (id, full_name, username, email, phone, password, role_id, company_id)
VALUES (90099, 'RLS Test 99', 'rls_test_99', 'rls99@test.local', '0000000099', 'x', 2, 1)
ON CONFLICT (id) DO NOTHING;

-- Switch to non-superuser application role so RLS is enforced
-- (postgres has BYPASSRLS, vyra_app does not)
GRANT INSERT, SELECT, UPDATE, DELETE ON dbsmart_sessions TO vyra_app;
GRANT USAGE, SELECT ON SEQUENCE dbsmart_sessions_id_seq TO vyra_app;
SET LOCAL ROLE vyra_app;

-- ============================================================
-- Insert one session as user 90042
-- ============================================================
SET LOCAL vyra.user_id = '90042';
SET LOCAL vyra.company_id = '1';
SET LOCAL vyra.is_admin = 'false';

INSERT INTO dbsmart_sessions (session_uid, user_id, company_id, source_id, current_step)
VALUES (gen_random_uuid(), 90042, 1, NULL, 0);

-- Cross-tenant write should be blocked by WITH CHECK
SAVEPOINT s1;
INSERT INTO dbsmart_sessions (session_uid, user_id, company_id, source_id, current_step)
VALUES (gen_random_uuid(), 90099, 1, NULL, 0);
ROLLBACK TO s1;

SELECT 'visible_as_user_42' AS who, COUNT(*) AS n FROM dbsmart_sessions WHERE user_id = 90042;

-- ============================================================
-- Switch perspective to user 90099 — should see 0 rows
-- ============================================================
SET LOCAL vyra.user_id = '90099';
SELECT 'visible_as_user_99' AS who, COUNT(*) AS n FROM dbsmart_sessions WHERE user_id = 90042;

-- ============================================================
-- Admin bypass: sees all
-- ============================================================
SET LOCAL vyra.user_id = '90099';
SET LOCAL vyra.is_admin = 'true';
SELECT 'visible_as_admin' AS who, COUNT(*) AS n FROM dbsmart_sessions WHERE user_id = 90042;

ROLLBACK;
