-- ============================================================
-- QRing — historique du sommeil (une ligne par nuit et par bague)
-- La GATEWAY RHM envoie toutes les nuits encore en mémoire dans la bague (≈ 7 jours) ;
-- chaque nuit est enregistrée une seule fois (mise à jour si elle revient).
-- À lancer une fois :  sudo -u postgres psql -d <base> -f sleep_migration.sql
-- ============================================================
CREATE TABLE IF NOT EXISTS ring_sleep_nights (
    id            BIGSERIAL PRIMARY KEY,
    ring_id       BIGINT NOT NULL REFERENCES rings(id) ON DELETE CASCADE,
    night_date    DATE NOT NULL,                 -- date du réveil
    start_at      TIMESTAMPTZ,                   -- coucher
    end_at        TIMESTAMPTZ,                   -- lever
    total_min     INTEGER NOT NULL DEFAULT 0,    -- profond + léger + REM + éveillé (comme l'app QRing)
    deep_min      INTEGER NOT NULL DEFAULT 0,
    light_min     INTEGER NOT NULL DEFAULT 0,
    rem_min       INTEGER NOT NULL DEFAULT 0,
    awake_min     INTEGER NOT NULL DEFAULT 0,
    phases        JSONB,                         -- [{start, end, type}] (deep/light/rem/awake)
    gateway       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ring_id, night_date)
);
CREATE INDEX IF NOT EXISTS ring_sleep_nights_date_idx ON ring_sleep_nights (ring_id, night_date DESC);

-- Droits pour l'utilisateur de l'application (remplacer iti si besoin)
GRANT SELECT, INSERT, UPDATE, DELETE ON ring_sleep_nights TO iti;
GRANT USAGE, SELECT ON SEQUENCE ring_sleep_nights_id_seq TO iti;
