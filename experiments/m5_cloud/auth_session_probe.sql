-- M5 owner-auth probe: probe role and session-check function (design §2.6, K1).
-- Synthetic project acyghoemtdrilsdszolq only. Apply as ONE migration (one transaction).
-- The role gets no password here; the owner sets it in the SQL editor (S2).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pft_m5_authprobe')
     OR to_regprocedure('pft_m5_probe.owner_session_alive(uuid,uuid)') IS NOT NULL THEN
    RAISE EXCEPTION 'm5_auth_probe objects already exist';
  END IF;
END $$;

CREATE ROLE pft_m5_authprobe LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 4;
ALTER ROLE pft_m5_authprobe SET default_transaction_read_only = on;
GRANT USAGE ON SCHEMA pft_m5_probe TO pft_m5_authprobe;
GRANT SELECT ON pft_m5_probe.identity TO pft_m5_authprobe;

CREATE FUNCTION pft_m5_probe.owner_session_alive(p_session uuid, p_owner uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
  SELECT EXISTS (SELECT 1 FROM auth.sessions s
                 WHERE s.id = p_session AND s.user_id = p_owner AND s.aal = 'aal2'
                   AND (s.not_after IS NULL OR s.not_after > now()))
$$;
REVOKE ALL ON FUNCTION pft_m5_probe.owner_session_alive(uuid, uuid)
  FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION pft_m5_probe.owner_session_alive(uuid, uuid) TO pft_m5_authprobe;
