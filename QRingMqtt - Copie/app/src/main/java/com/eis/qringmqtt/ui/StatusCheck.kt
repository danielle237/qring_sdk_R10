package com.eis.qringmqtt.ui

import androidx.compose.ui.graphics.Color
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Command
import com.eis.qringmqtt.data.Err
import com.eis.qringmqtt.data.Reading
import com.eis.qringmqtt.data.RingConn
import com.eis.qringmqtt.data.Source
import com.eis.qringmqtt.data.tr
import com.eis.qringmqtt.service.CommandProcessor
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * « État de la bague » : même logique que le bouton État du bot Telegram et de la Web App.
 *
 * Vérification (bouton Actualiser de l'accueil / « État bague » du menu / popup « Content de vous revoir ») :
 *  - la batterie est lue en premier (la carte Batterie est mise à jour) ;
 *  - bague hors portée / Bluetooth coupé / aucune bague : affiché tout de suite, rien n'est lancé ;
 *  - port vérifié il y a moins de REUSE_MS : réutilisé ;
 *  - une mesure tourne déjà : on la suit (elle sert de vérification) ;
 *  - sinon une mesure HR est lancée : WEAR_MS sans problème => « portée » (la mesure continue),
 *    « retirée » si la bague le signale.
 * Pas de compte à rebours : si une mesure vient d'être faite (REUSE_MS) ou tourne déjà,
 * un popup l'explique (« Vous venez de faire une mesure » / « Mesure en cours, patientez »).
 *
 * En permanence (même sans vérification) : état de la bague pour le bandeau et la carte du menu,
 * et les 3 popups (hors portée, retirée, reconnectée).
 */
object StatusCheck {

    const val WEAR_MS = 15_000L
    const val REUSE_MS = 120_000L
    const val COOLDOWN_MS = 180_000L
    /** Coupure plus longue que ce délai => popup « bague éloignée » (évite les micro-coupures). */
    const val OUT_POPUP_DELAY_MS = 10_000L
    /** Popups « retirée » et « reconnectée » fermés tout seuls après ce délai. */
    const val POPUP_AUTO_CLOSE_MS = 30_000L
    private const val TIMEOUT_MARGIN_MS = 30_000L

    // ------------------------------------------------------------------ vérification en cours

    enum class Phase { REQUESTED, CHECKING, WORN_MEASURING, WORN, REMOVED, OUT, BT_OFF, NO_RING, UNCONFIRMED, FAILED }

    data class State(
        val phase: Phase,
        val cmd: Cmd = Cmd.HR,
        val startedMs: Long = System.currentTimeMillis(),
        /** Début de la mesure suivie (pour le compteur). */
        val measureStartMs: Long? = null,
        val wornAtMs: Long? = null,
        val value: String? = null,
        val error: String? = null,
        val reused: Boolean = false,
        /** true = mesure déjà lancée par quelqu'un d'autre, suivie. */
        val followed: Boolean = false,
        val final: Boolean = false,
        val finalAtMs: Long? = null
    )

    val state = MutableStateFlow<State?>(null)

    /** Le bouton ne peut pas relancer avant cette heure (ms). */
    val cooldownUntil = MutableStateFlow(0L)

    val running: Boolean get() = state.value?.final == false

    // ------------------------------------------------------------------ preuves (connexion actuelle)

    /**
     * Ce que l'on sait de la bague depuis sa dernière (re)connexion.
     * Remis à zéro quand la bague revient après une vraie perte (popup affiché).
     */
    data class Evidence(
        /** 0 = jamais connectée depuis le démarrage de l'app. */
        val connectedSinceMs: Long = 0L,
        /** Début de la coupure en cours (null = connectée). */
        val lostAtMs: Long? = null,
        val wornAtMs: Long? = null,
        val removedAtMs: Long? = null,
        /** Dernière valeur obtenue (« ❤️ 72 bpm »). */
        val valueText: String? = null
    )

    val evidence = MutableStateFlow(Evidence())

    // ------------------------------------------------------------------ popups

    enum class PopupKind { OUT, REMOVED, RECONNECTED, RECENT, BUSY }

    data class Popup(
        val kind: PopupKind,
        val atMs: Long,
        /** Mesure concernée (popup « retirée »). */
        val cmd: Cmd? = null,
        /** La mesure retirée venait de la vérification « État bague ». */
        val fromCheck: Boolean = false,
        /** Détail affiché (popup « Vous venez de faire une mesure »). */
        val text: String? = null
    )

    val popup = MutableStateFlow<Popup?>(null)

    fun dismissPopup() {
        popup.value = null
    }

    // ------------------------------------------------------------------ surveillance permanente

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var job: Job? = null
    private var lostJob: Job? = null
    private var started = false
    /** Popup « éloignée » déjà montré pour la coupure en cours => popup « reconnectée » au retour. */
    private var outShown = false
    private var markedMeasureStart = 0L

    /** À appeler une fois (App.onCreate). */
    fun init() {
        if (started) return
        started = true
        val t0 = System.currentTimeMillis()

        // 1) connexion Bluetooth de la bague
        scope.launch {
            AppState.ring.collect { r -> onRing(r) }
        }

        // 2) résultats des mesures (lancées via TV ou à distance)
        scope.launch {
            AppState.lastResult.collect { res ->
                if (res == null || res.atMs < t0) return@collect
                if (res.ok && res.cmd.measure) {
                    val v = valueText(res.cmd, res.values)
                    evidence.update { it.copy(wornAtMs = maxOf(it.wornAtMs ?: 0L, res.atMs), valueText = v ?: it.valueText) }
                } else if (res.error == Err.RING_REMOVED) {
                    evidence.update { it.copy(removedAtMs = res.atMs) }
                    val fromCheck = isCheckResult(state.value, res.cmd, res.atMs)
                    popup.value = Popup(PopupKind.REMOVED, res.atMs, res.cmd, fromCheck)
                }
            }
        }

        // 3) toutes les secondes : règle des 15 s pour toute mesure en cours + fermeture auto des popups
        scope.launch {
            while (true) {
                delay(1000)
                val now = System.currentTimeMillis()
                val a = AppState.active.value
                if (a != null && a.startedAtMs != markedMeasureStart &&
                    AppState.ring.value == RingConn.CONNECTED && now - a.startedAtMs >= WEAR_MS
                ) {
                    markedMeasureStart = a.startedAtMs
                    evidence.update { it.copy(wornAtMs = maxOf(it.wornAtMs ?: 0L, now)) }
                }
                val p = popup.value
                if (p != null && p.kind != PopupKind.OUT && now - p.atMs > POPUP_AUTO_CLOSE_MS) popup.value = null
            }
        }
    }

    private fun onRing(r: RingConn) {
        val now = System.currentTimeMillis()
        when (r) {
            RingConn.CONNECTED -> {
                lostJob?.cancel()
                val ev = evidence.value
                when {
                    // Premier contact depuis le démarrage de l'app
                    ev.connectedSinceMs == 0L -> evidence.value = Evidence(connectedSinceMs = now)
                    // Retour après une vraie perte : on repart de zéro et on propose la vérification
                    outShown -> {
                        evidence.value = Evidence(connectedSinceMs = now)
                        cooldownUntil.value = 0L
                        popup.value = Popup(PopupKind.RECONNECTED, now)
                    }
                    // Micro-coupure : on garde ce qu'on savait
                    else -> evidence.update { it.copy(lostAtMs = null) }
                }
                outShown = false
            }
            RingConn.NO_RING -> {
                lostJob?.cancel()
                outShown = false
                evidence.value = Evidence()
                popup.value = null
                cooldownUntil.value = 0L
            }
            else -> {
                // Hors portée (DISCONNECTED / CONNECTING) ou Bluetooth coupé
                val ev = evidence.value
                if (ev.connectedSinceMs == 0L) return          // pas encore connectée depuis le démarrage
                if (ev.lostAtMs == null) {
                    evidence.update { it.copy(lostAtMs = now) }
                    lostJob?.cancel()
                    lostJob = scope.launch {
                        delay(OUT_POPUP_DELAY_MS)
                        val cur = AppState.ring.value
                        if (cur != RingConn.CONNECTED && cur != RingConn.NO_RING) {
                            outShown = true
                            // Pas de popup « éloignée » pour le Bluetooth de la TV coupé (le bandeau le dit)
                            if (cur != RingConn.BLUETOOTH_OFF) popup.value = Popup(PopupKind.OUT, System.currentTimeMillis())
                        }
                    }
                }
            }
        }
    }

    /** Ce résultat est-il celui de la mesure lancée par la vérification (pas une mesure suivie ni plus récente) ? */
    fun isCheckResult(s: State?, cmd: Cmd, atMs: Long): Boolean =
        s != null && !s.followed && s.cmd == cmd && atMs >= s.startedMs - 1000 &&
            (!s.final || atMs <= (s.finalAtMs ?: 0L) + 1000)

    // ------------------------------------------------------------------ bouton

    /** Le bouton peut-il être utilisé maintenant ? (il clignote quand c'est le cas) */
    fun canStart(ring: RingConn, st: State?, cooldown: Long, nowMs: Long): Boolean =
        ring != RingConn.NO_RING && st?.final != false && !waiting.value

    /** Vérification demandée pendant une autre mesure : elle sera lancée à la fin de celle-ci. */
    val waiting = MutableStateFlow(false)
    private var waitJob: Job? = null

    /**
     * Lance la vérification.
     * @param force true = ignore l'attente de 3 min (popup « Content de vous revoir »).
     */
    fun start(force: Boolean = false) {
        if (running) return
        val now = System.currentTimeMillis()
        val ring = AppState.ring.value

        // 1) ce qu'on sait sans mesurer (pas d'attente ensuite : rien n'a été demandé à la bague)
        val immediate = when (ring) {
            RingConn.NO_RING -> Phase.NO_RING
            RingConn.BLUETOOTH_OFF -> Phase.BT_OFF
            RingConn.CONNECTED -> null
            else -> Phase.OUT
        }
        if (immediate != null) {
            state.value = State(immediate, final = true, finalAtMs = now)
            return
        }

        // 2) une mesure tourne déjà : « veuillez patienter », la vérification est lancée juste après
        val active = AppState.active.value
        if (active != null) {
            popup.value = Popup(PopupKind.BUSY, now, active.cmd, text = active.cmd.label)
            if (!waiting.value) {
                waiting.value = true
                waitJob?.cancel()
                waitJob = scope.launch {
                    try {
                        while (AppState.active.value != null) delay(500)
                        delay(1000)
                        if (popup.value?.kind == PopupKind.BUSY) popup.value = null
                    } finally {
                        waiting.value = false
                    }
                    start(force = true)
                }
            }
            return
        }

        // 3) la batterie d'abord, puis une mesure HR (file de commandes)
        CommandProcessor.submit(Command(Cmd.BATTERY, null, Source.MANUAL))
        CommandProcessor.submit(Command(Cmd.HR, null, Source.MANUAL))
        state.value = State(Phase.REQUESTED, cmd = Cmd.HR, startedMs = now)

        job?.cancel()
        job = scope.launch { track() }
    }

    private fun finish(s: State) {
        val now = System.currentTimeMillis()
        state.value = s.copy(final = true, finalAtMs = now)
    }

    private suspend fun track() {
        var seenActive = false
        var goneSinceMs = 0L
        while (true) {
            delay(500)
            val s = state.value ?: return
            if (s.final) return
            val now = System.currentTimeMillis()
            val res = AppState.lastResult.value
            val active = AppState.active.value

            // Résultat de la mesure suivie
            if (res != null && res.cmd == s.cmd && res.atMs >= s.startedMs - 1000) {
                if (res.ok) {
                    finish(s.copy(phase = Phase.WORN, wornAtMs = s.wornAtMs ?: res.atMs, value = valueText(s.cmd, res.values)))
                } else when (res.error) {
                    Err.RING_REMOVED -> finish(s.copy(phase = Phase.REMOVED))
                    Err.RING_DISCONNECTED -> finish(s.copy(phase = Phase.OUT))
                    // Port déjà vérifié : la bague reste « portée », seule la mesure a échoué
                    else -> if (s.wornAtMs != null) finish(s.copy(phase = Phase.WORN, error = res.error))
                    else finish(s.copy(phase = Phase.FAILED, error = res.error))
                }
                return
            }

            // Bague perdue pendant la vérification
            if (AppState.ring.value != RingConn.CONNECTED) {
                finish(s.copy(phase = Phase.OUT))
                return
            }

            // Mesure démarrée puis terminée sans résultat (annulée, erreur) : pas d'attente inutile
            if (active != null && active.cmd == s.cmd) {
                seenActive = true
                goneSinceMs = 0L
            } else if (seenActive) {
                if (goneSinceMs == 0L) goneSinceMs = now
                else if (now - goneSinceMs > 2000) {
                    val cur = state.value ?: s
                    if (cur.wornAtMs != null) finish(cur.copy(phase = Phase.WORN, error = Err.MEASURE_FAILED))
                    else finish(cur.copy(phase = Phase.FAILED, error = Err.MEASURE_FAILED))
                    return
                }
            }

            if (active != null && active.cmd == s.cmd) {
                val elapsed = now - active.startedAtMs
                var next = s.copy(measureStartMs = active.startedAtMs)
                // WEAR_MS de mesure sans « retirée » => bague portée (la mesure continue)
                if (next.wornAtMs == null && elapsed >= WEAR_MS) {
                    next = next.copy(wornAtMs = now)
                    evidence.update { it.copy(wornAtMs = maxOf(it.wornAtMs ?: 0L, now)) }
                }
                state.value = next.copy(phase = if (next.wornAtMs != null) Phase.WORN_MEASURING else Phase.CHECKING)
            }

            // Sécurité : rien ne revient. Compté depuis le début réel de la mesure ;
            // avant son démarrage (file d'attente : batterie, synchro…) on laisse plus de temps.
            val cur0 = state.value ?: s
            val limitFrom = cur0.measureStartMs ?: cur0.startedMs
            val limit = cur0.cmd.durationSec * 1000L + TIMEOUT_MARGIN_MS + (if (cur0.measureStartMs == null) 90_000L else 0L)
            if (now - limitFrom > limit) {
                val cur = state.value ?: s
                if (cur.wornAtMs != null) finish(cur.copy(phase = Phase.WORN, error = Err.TIMEOUT))
                else finish(cur.copy(phase = Phase.UNCONFIRMED))
                return
            }
        }
    }

    // ------------------------------------------------------------------ présentation

    enum class Look { WORN, REMOVED, OUT, BT_OFF, UNCHECKED, CHECKING, CONNECTING, NO_RING }

    /**
     * État à afficher (bandeau de la bague, carte « Bague » du menu).
     * [short] : « Portée » ; [title] : « Bague portée » ; [detail] : « vérifiée à 14:41 · ❤️ 72 bpm ».
     */
    data class Summary(val look: Look, val color: Color, val short: String, val title: String, val detail: String?, val progress: Float? = null)

    fun summary(ring: RingConn, ev: Evidence, st: State?, nowMs: Long): Summary {
        fun hm(ms: Long) = hhmmss(ms).substring(0, 5)
        when (ring) {
            RingConn.NO_RING -> return Summary(Look.NO_RING, C.muted, tr("rs.no_ring"), tr("rs.no_ring"), null)
            RingConn.BLUETOOTH_OFF -> return Summary(Look.BT_OFF, C.err, tr("rs.bt_off"), tr("rs.bt_off"), tr("home.bt_off_text"))
            RingConn.CONNECTED -> {}
            else -> {
                if (ev.connectedSinceMs == 0L) return Summary(Look.CONNECTING, C.muted, tr("rs.connecting"), tr("rs.connecting"), null)
                val since = ev.lostAtMs ?: nowMs
                return Summary(Look.OUT, C.err, tr("rs.out"), tr("rs.out_title"), tr("rs.out_detail", hm(since)))
            }
        }

        // Vérification en cours
        if (st != null && !st.final) {
            val elapsed = st.measureStartMs?.let { ((nowMs - it) / 1000).toInt().coerceAtLeast(0) } ?: 0
            val wearSec = (WEAR_MS / 1000).toInt()
            return if (st.phase == Phase.WORN_MEASURING) {
                Summary(Look.WORN, C.ok, tr("rs.worn"), tr("rs.worn_title"),
                    tr("st.measuring", st.cmd.label, elapsed, st.cmd.durationSec), elapsed / st.cmd.durationSec.toFloat())
            } else {
                Summary(Look.CHECKING, C.accent, tr("rs.checking"), tr("st.checking"),
                    if (st.phase == Phase.REQUESTED) (if (st.followed) tr("st.follow", st.cmd.label) else tr("st.request"))
                    else "$elapsed s / $wearSec s",
                    if (st.phase == Phase.CHECKING) elapsed / wearSec.toFloat() else null)
            }
        }

        val worn = ev.wornAtMs?.takeIf { it >= ev.connectedSinceMs }
        val removed = ev.removedAtMs?.takeIf { it >= ev.connectedSinceMs }
        return when {
            removed != null && removed >= (worn ?: 0L) ->
                Summary(Look.REMOVED, C.warn, tr("rs.removed"), tr("rs.removed_title"), tr("rs.removed_detail", hm(removed)))
            worn != null ->
                Summary(Look.WORN, C.ok, tr("rs.worn"), tr("rs.worn_title"),
                    listOfNotNull(tr("rs.checked_at", hm(worn)), ev.valueText).joinToString(" · "))
            st != null && st.final && (st.phase == Phase.UNCONFIRMED || st.phase == Phase.FAILED) &&
                (st.finalAtMs ?: 0L) >= ev.connectedSinceMs ->
                Summary(Look.UNCHECKED, C.accent, tr("rs.unchecked"), tr("rs.unchecked_title"),
                    if (st.phase == Phase.UNCONFIRMED) tr("st.unconfirmed") else tr("st.failed", Err.label(st.error ?: Err.MEASURE_FAILED)))
            // Ouverture de l'app / reconnexion : on dit seulement si la bague est connectée
            else ->
                Summary(Look.UNCHECKED, C.accent, tr("rs.unchecked"), tr("rs.unchecked_title"), null)
        }
    }

    /** « 2:47 » */
    fun countdown(untilMs: Long, nowMs: Long): String {
        val s = ((untilMs - nowMs + 999) / 1000).coerceAtLeast(0)
        return "%d:%02d".format(s / 60, s % 60)
    }

    private fun valueText(cmd: Cmd, values: org.json.JSONObject?): String? {
        if (values == null) return null
        if (cmd == Cmd.ALL) {
            val hr = values.optInt("hr")
            return if (hr > 0) "❤️ $hr bpm" else null
        }
        val m = METRICS.firstOrNull { it.cmd == cmd } ?: return null
        val main = formatReading(m, Reading(m.key, values, 0, Source.MANUAL)).first
        val icon = when (cmd) { Cmd.HR -> "❤️ "; Cmd.SPO2 -> "💧 "; Cmd.TEMP -> "🌡 "; else -> "" }
        return icon + (if (m.unit.isNotBlank()) "$main ${m.unit}" else main)
    }
}
