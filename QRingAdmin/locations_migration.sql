-- ============================================================
-- GATEWAY RHM — historique des déplacements des bagues
--
-- Une ligne seulement quand quelque chose CHANGE (pas à chaque tour test_reachable) :
--   arrival      : la bague est entendue sur une autre Pi (changement de pièce)
--   out_of_range : plus aucune Pi de ses zones ne l'entend (hors portée)
--   back         : de nouveau entendue après « hors portée »
-- prev_gateway_id = Pi où elle était avant (pour « arrival »).
-- Rien n'est supprimé ni modifié dans les tables existantes.
-- À lancer une fois :  sudo -u postgres psql -d <base> -f locations_migration.sql
-- (relançable sans risque : IF NOT EXISTS partout)
-- ============================================================
BEGIN;

CREATE TABLE IF NOT EXISTS ring_locations (
    id               BIGSERIAL PRIMARY KEY,
    time             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ring_id          BIGINT NOT NULL REFERENCES rings(id)    ON DELETE CASCADE,
    gateway_id       BIGINT          REFERENCES gateways(id) ON DELETE SET NULL,
    prev_gateway_id  BIGINT          REFERENCES gateways(id) ON DELETE SET NULL,
    event            TEXT   NOT NULL CHECK (event IN ('arrival', 'out_of_range', 'back')),
    rssi             SMALLINT
);

CREATE INDEX IF NOT EXISTS ring_locations_ring_time ON ring_locations (ring_id, time DESC);

COMMIT;

-- Exemple : déplacements de la bague 30:32:42:32:64:01 sur 24 h
-- SELECT l.time, l.event, g.name AS gateway, COALESCE(g.zone_name, g.name) AS piece, p.name AS avant, l.rssi
--   FROM ring_locations l JOIN rings r ON r.id = l.ring_id
--   LEFT JOIN gateways g ON g.id = l.gateway_id LEFT JOIN gateways p ON p.id = l.prev_gateway_id
--  WHERE r.mac = '30:32:42:32:64:01' AND l.time > NOW() - INTERVAL '24 hours' ORDER BY l.time DESC;
