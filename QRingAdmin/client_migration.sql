-- ============================================================
-- QRingClient (app téléphone) — tables des comptes, droits, téléphones et alertes
-- À lancer UNE fois :  psql -h 127.0.0.1 -U iti -d smart_ring -f client_migration.sql
-- Ne supprime et ne modifie rien d'existant (CREATE ... IF NOT EXISTS uniquement).
-- ============================================================

-- Comptes de l'app (créés par l'administrateur dans QRing Admin)
CREATE TABLE IF NOT EXISTS client_users (
    id             BIGSERIAL PRIMARY KEY,
    login          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    display_name   TEXT,
    lang           TEXT NOT NULL DEFAULT 'fr',
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    -- interrupteur général « Recevoir les alertes » (choix de l'utilisateur dans l'app)
    alerts_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    -- incrémenté au changement de mot de passe / désactivation : déconnecte tous les téléphones
    token_version  INTEGER NOT NULL DEFAULT 1,
    failed_logins  INTEGER NOT NULL DEFAULT 0,
    locked_until   TIMESTAMPTZ,
    last_login_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Bagues affectées à un compte + droits
CREATE TABLE IF NOT EXISTS client_ring_access (
    id                 BIGSERIAL PRIMARY KEY,
    client_user_id     BIGINT NOT NULL REFERENCES client_users(id) ON DELETE CASCADE,
    ring_id            BIGINT NOT NULL REFERENCES rings(id) ON DELETE CASCADE,
    label              TEXT,                       -- nom affiché dans l'app (ex. « Papa »)
    can_view_history   BOOLEAN NOT NULL DEFAULT TRUE,
    can_live           BOOLEAN NOT NULL DEFAULT TRUE,   -- lancer des mesures
    allowed_measures   TEXT[],                     -- NULL = toutes ; sinon hr, spo2, temp, bp, hrv, stress, steps
    can_receive_alerts BOOLEAN NOT NULL DEFAULT TRUE,   -- droit donné par l'admin
    notify             BOOLEAN NOT NULL DEFAULT TRUE,   -- choix de l'utilisateur pour cette bague
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (client_user_id, ring_id)
);
CREATE INDEX IF NOT EXISTS client_ring_access_ring_idx ON client_ring_access (ring_id);

-- Téléphones (jeton Firebase Cloud Messaging) pour les notifications app fermée
CREATE TABLE IF NOT EXISTS client_devices (
    id             BIGSERIAL PRIMARY KEY,
    client_user_id BIGINT NOT NULL REFERENCES client_users(id) ON DELETE CASCADE,
    fcm_token      TEXT NOT NULL UNIQUE,
    platform       TEXT,
    app_version    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS client_devices_user_idx ON client_devices (client_user_id);

-- Alertes envoyées (liste « Alertes » de l'app)
CREATE TABLE IF NOT EXISTS client_alerts (
    id         BIGSERIAL PRIMARY KEY,
    ring_id    BIGINT REFERENCES rings(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,   -- removed, out_of_range, gateway_offline, battery_low, restored_range, restored_gateway
    title      TEXT,
    message    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS client_alerts_ring_idx ON client_alerts (ring_id, created_at DESC);
