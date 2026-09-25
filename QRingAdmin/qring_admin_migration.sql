-- ============================================================
-- QRing Admin — droits par mesure (optionnel)
-- Ajoute UNE colonne à ring_telegram_access. Rien n'est supprimé ni modifié.
--   NULL                  = toutes les mesures (droit général can_live)
--   {'hr','spo2','temp'}  = seulement ces mesures
-- Valeurs possibles : hr, spo2, temp, bp, hrv, stress, all
-- ============================================================
ALTER TABLE ring_telegram_access
    ADD COLUMN IF NOT EXISTS allowed_measures TEXT[] NULL;
