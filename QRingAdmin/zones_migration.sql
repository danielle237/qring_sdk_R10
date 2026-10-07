-- ============================================================
-- GATEWAY RHM — zones des bagues (V2)
--
-- Une zone = une Gateway RHM (une Pi) avec un nom de pièce : « Chambre 12 », « Salon »…
-- Chaque bague a :
--   * 1 zone principale    (position 0) : la chambre du résident
--   * 0 à 2 zones secondaires (positions 1 et 2) : salon, salle à manger…
-- La base l'impose : une seule zone principale, au plus deux secondaires, pas deux fois la même gateway.
--
-- Le nom du résident (« Mme Martin ») existe déjà : « Nom affiché » de « Bagues et droits ».
-- Rien n'est supprimé ni modifié dans les tables existantes : seulement des colonnes / une table ajoutées.
-- À lancer une fois :  sudo -u postgres psql -d <base> -f zones_migration.sql
-- (relançable sans risque : IF NOT EXISTS partout)
-- ============================================================
BEGIN;

-- Nom de la pièce affiché dans l'app (la colonne « location » reste celle du nom d'appareil Android)
ALTER TABLE gateways ADD COLUMN IF NOT EXISTS zone_name TEXT;
-- Type de gateway : 'linux' (Pi) ou 'android' (TV) — NULL = inconnu
ALTER TABLE gateways ADD COLUMN IF NOT EXISTS gateway_type TEXT;

CREATE TABLE IF NOT EXISTS ring_zones (
    id          BIGSERIAL PRIMARY KEY,
    ring_id     BIGINT   NOT NULL REFERENCES rings(id)    ON DELETE CASCADE,
    gateway_id  BIGINT   NOT NULL REFERENCES gateways(id) ON DELETE CASCADE,
    position    SMALLINT NOT NULL CHECK (position BETWEEN 0 AND 2),   -- 0 = principale, 1-2 = secondaires
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ring_id, position),      -- une seule principale, deux secondaires max
    UNIQUE (ring_id, gateway_id)     -- une gateway une seule fois par bague
);
CREATE INDEX IF NOT EXISTS ring_zones_gateway_idx ON ring_zones (gateway_id);

-- Vue pratique : zones de chaque bague, avec MAC et nom de gateway
CREATE OR REPLACE VIEW v_ring_zones AS
SELECT r.mac::text            AS mac,
       r.name                 AS ring_name,
       z.position,
       CASE WHEN z.position = 0 THEN 'main' ELSE 'secondary' END AS role,
       g.name                 AS gateway,
       COALESCE(NULLIF(g.zone_name, ''), g.name) AS zone_name,
       g.gateway_type
  FROM ring_zones z
  JOIN rings    r ON r.id = z.ring_id
  JOIN gateways g ON g.id = z.gateway_id;

-- Droits pour l'utilisateur de l'application (remplacer iti si besoin)
GRANT SELECT, INSERT, UPDATE, DELETE ON ring_zones TO iti;
GRANT USAGE, SELECT ON SEQUENCE ring_zones_id_seq TO iti;
GRANT SELECT ON v_ring_zones TO iti;
GRANT UPDATE (zone_name, gateway_type) ON gateways TO iti;

COMMIT;
