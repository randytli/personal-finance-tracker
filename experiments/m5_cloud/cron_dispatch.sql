-- M5 cron acceptance dispatch (synthetic project acyghoemtdrilsdszolq only).
-- Requires pg_cron, pg_net, supabase_vault and pgcrypto (schema "extensions").
-- Secrets are never written here: the HMAC key and the Vercel automation-bypass
-- value are loaded into Vault separately (see the evidence README) and read only
-- inside pft_ops.dispatch_tick, which runs as the cron job owner (postgres).

CREATE SCHEMA IF NOT EXISTS pft_ops;
REVOKE ALL ON SCHEMA pft_ops FROM PUBLIC;

-- Same signer as experiments/m5_cloud/trigger_cron.sql.template ({crypto} = extensions),
-- which tests/test_m5_trigger_auth.py verifies against api.trigger_auth.verify.
CREATE OR REPLACE FUNCTION pft_ops.trigger_signature(
    p_secret text, p_audience text, p_kid text, p_path text, p_kind text)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
    v_ts bigint := floor(extract(epoch FROM clock_timestamp()));
    v_nonce text := encode(extensions.gen_random_bytes(16), 'hex');
    v_body text;
BEGIN
    IF p_kind !~ '^[a-z]+$' OR p_kid !~ '^[a-z0-9_-]{1,32}$' THEN
        RAISE EXCEPTION 'invalid trigger kind or key id';
    END IF;
    v_body := '{"kind":"' || p_kind || '"}';
    RETURN format('kid=%s,ts=%s,nonce=%s,sig=%s', p_kid, v_ts, v_nonce, encode(extensions.hmac(
        convert_to(concat_ws(E'\n', 'pft-trigger-v1', p_audience, p_kid, v_ts::text, v_nonce,
                             'POST', p_path,
                             encode(extensions.digest(convert_to(v_body, 'UTF8'), 'sha256'), 'hex')),
                   'UTF8'),
        convert_to(p_secret, 'UTF8'), 'sha256'), 'hex'));
END
$fn$;
REVOKE ALL ON FUNCTION pft_ops.trigger_signature(text, text, text, text, text) FROM PUBLIC;

-- Pinned target. Not secret; owner-only.
CREATE TABLE IF NOT EXISTS pft_ops.trigger_target (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    url text NOT NULL CHECK (url ~ '^https://pft-m5-jobs-20261001-[a-z0-9-]+\.vercel\.app/trigger$'),
    audience text NOT NULL CHECK (audience = 'pft-jobs-m5-synthetic'));
REVOKE ALL ON pft_ops.trigger_target FROM PUBLIC;

-- One signed delivery through pg_net. Returns the net request id. The net
-- response is delivery evidence only; durable sync_runs decide the outcome.
CREATE OR REPLACE FUNCTION pft_ops.dispatch_tick(p_timeout_ms integer DEFAULT 300000,
                                                 p_source text DEFAULT 'cron')
RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
    v_target pft_ops.trigger_target;
BEGIN
    IF p_timeout_ms NOT BETWEEN 1000 AND 300000 OR p_source !~ '^[a-z0-9-]{1,32}$' THEN
        RAISE EXCEPTION 'dispatch bounds rejected';
    END IF;
    SELECT * INTO STRICT v_target FROM pft_ops.trigger_target WHERE singleton;
    RETURN net.http_post(
        url := v_target.url,
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'x-pft-delivery-source', p_source,
            'x-vercel-protection-bypass',
                (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'm5_vercel_bypass'),
            'x-pft-trigger-signature', pft_ops.trigger_signature(
                (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'm5_trigger_key_v1'),
                v_target.audience, 'v1', '/trigger', 'tick')),
        body := '{"kind":"tick"}'::jsonb,
        timeout_milliseconds := p_timeout_ms);
END
$fn$;
REVOKE ALL ON FUNCTION pft_ops.dispatch_tick(integer, text) FROM PUBLIC;

-- Schedules are created separately, for bounded windows only:
--   SELECT cron.schedule('pft-m5-tick', '*/5 * * * *', $$SELECT pft_ops.dispatch_tick()$$);
--   SELECT cron.schedule('pft-m5-history-prune', '17 3 * * *',
--     $$DELETE FROM cron.job_run_details WHERE end_time < now() - interval '14 days'$$);
