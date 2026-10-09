-- Teardown for auth_session_probe.sql (design §6, S7). Remove the Vercel deployments first.
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'pft_m5_authprobe';
REVOKE ALL ON FUNCTION pft_m5_probe.owner_session_alive(uuid, uuid) FROM pft_m5_authprobe;
REVOKE ALL ON pft_m5_probe.identity FROM pft_m5_authprobe;
REVOKE ALL ON SCHEMA pft_m5_probe FROM pft_m5_authprobe;
DROP FUNCTION pft_m5_probe.owner_session_alive(uuid, uuid);
DROP ROLE pft_m5_authprobe;
