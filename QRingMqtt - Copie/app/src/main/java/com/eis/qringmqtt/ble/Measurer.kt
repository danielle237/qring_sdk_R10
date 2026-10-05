package com.eis.qringmqtt.ble

import android.util.Log
import com.eis.qringmqtt.data.Cmd
import com.eis.qringmqtt.data.Err
import com.oudmon.ble.base.bluetooth.BleOperateManager
import com.oudmon.ble.base.communication.ICommandResponse
import com.oudmon.ble.base.communication.rsp.StartHeartRateRsp
import com.oudmon.ble.base.communication.rsp.StopHeartRateRsp
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONObject
import kotlin.coroutines.resume

/**
 * Mesures manuelles sur la bague (cœur, SpO2, température, tension, HRV, stress, tout).
 *
 * La bague renvoie plusieurs réponses pendant une mesure (valeurs à 0 pendant la
 * progression, puis valeurs réelles). On garde la dernière valeur valide et on
 * termine quand la valeur est stable, ou à la fin du temps imparti.
 */
object Measurer {

    private const val TAG = "Measurer"

    sealed class Outcome {
        data class Ok(val values: JSONObject) : Outcome()
        data class Fail(val code: String) : Outcome()
    }

    private var session: Session? = null

    /** Plus de réponse de la bague pendant ce temps = mesure terminée côté SDK. */
    private const val IDLE_END_MS = 12_000L

    /** Lance une mesure et attend son résultat. [onLive] reçoit la valeur en direct (cœur). */
    suspend fun measure(cmd: Cmd, onLive: (String) -> Unit): Outcome =
        suspendCancellableCoroutine { cont ->
            mainHandler.post {
                session?.finish(Outcome.Fail(Err.CANCELLED))
                val s = Session(cmd, cont, onLive)
                session = s
                s.start()
            }
            cont.invokeOnCancellation {
                mainHandler.post { session?.let { if (it.cmd == cmd) it.finish(Outcome.Fail(Err.CANCELLED)) } }
            }
        }

    /** Arrête la mesure en cours (commande cancel ou bouton Annuler). */
    fun cancel() {
        mainHandler.post { session?.finish(Outcome.Fail(Err.CANCELLED)) }
    }

    // ------------------------------------------------------------------ session de mesure

    private class Session(
        val cmd: Cmd,
        val cont: CancellableContinuation<Outcome>,
        val onLive: (String) -> Unit
    ) {
        private var done = false
        private var validCount = 0
        private var best: JSONObject? = null
        /** Réponses reçues de la bague sans valeur exploitable (capteur sans signal). */
        private var emptyResponses = 0
        /** Temps maximum : cœur 60 s, SpO2 90 s (voir Cmd.durationSec). */
        private val hardTimeoutMs = cmd.durationSec * 1000L

        /** Fin de mesure : valeur obtenue, bague retirée (réponses sans signal) ou pas de réponse. */
        private val timeout = Runnable {
            val b = best
            finish(
                when {
                    b != null -> Outcome.Ok(b)
                    // La bague répond mais le capteur ne voit rien : bague retirée
                    emptyResponses > 0 -> Outcome.Fail(Err.RING_REMOVED)
                    else -> Outcome.Fail(Err.TIMEOUT)
                }
            )
        }
        private val settle = Runnable { best?.let { finish(Outcome.Ok(it)) } }

        /**
         * Une seule tentative, pas de relance automatique.
         * Le SDK arrête lui-même la mesure vers 30 s : si la bague ne répond plus
         * pendant [IDLE_END_MS], on affiche tout de suite le résultat (ou l'échec)
         * sans attendre le temps maximum (cœur 60 s, SpO2 90 s).
         */
        private val idleEnd = Runnable { timeout.run() }

        private fun gotResponse() {
            mainHandler.removeCallbacks(idleEnd)
            mainHandler.postDelayed(idleEnd, IDLE_END_MS)
        }

        fun start() {
            mainHandler.postDelayed(timeout, hardTimeoutMs)
            startOnRing()
        }

        private fun startOnRing() {
            val bom = BleOperateManager.getInstance()
            try {
                when (cmd) {
                    Cmd.HR -> bom.manualModeHeart(startCb, false)
                    Cmd.SPO2 -> bom.manualModeSpO2(startCb, false)
                    Cmd.TEMP -> bom.manualTemperature(startCb, false)
                    Cmd.BP -> bom.manualModeBP(startCb, false)
                    Cmd.HRV -> bom.manualModeHrv(startCb, false)
                    Cmd.STRESS -> bom.manualModePressure(startCb, false)
                    Cmd.ALL -> bom.oneClickMeasurement(allCb, false)
                    else -> finish(Outcome.Fail(Err.UNKNOWN_COMMAND))
                }
            } catch (e: Exception) {
                Log.e(TAG, "start $cmd", e)
                finish(Outcome.Fail(Err.MEASURE_FAILED))
            }
        }

        // Réponses des mesures simples
        private val startCb = ICommandResponse<StartHeartRateRsp> { r ->
            mainHandler.post { onStart(r) }
        }

        // Réponses de la mesure « tout en un »
        private val allCb = ICommandResponse<StopHeartRateRsp> { r ->
            mainHandler.post { onAll(r) }
        }

        private fun onStart(r: StartHeartRateRsp) {
            if (done) return
            gotResponse()
            if (r.errCode.toInt() != 0) {
                // Erreur capteur = pas de contact avec le doigt
                val b = best
                finish(if (b != null) Outcome.Ok(b) else Outcome.Fail(Err.RING_REMOVED))
                return
            }
            val v = r.value
            val values: JSONObject = when (cmd) {
                Cmd.HR -> if (v > 0) JSONObject().put("value", v).put("unit", "bpm")
                    .apply { if (r.rri > 0) put("rri", r.rri) } else null
                Cmd.SPO2 -> if (v > 0) JSONObject().put("value", v).put("unit", "%") else null
                Cmd.TEMP -> tempC(if (v > 0) v else r.temperature)
                    ?.let { JSONObject().put("value", it).put("unit", "°C") }
                Cmd.BP -> if (r.sbp > 0 && r.dbp > 0)
                    JSONObject().put("sbp", r.sbp).put("dbp", r.dbp).put("unit", "mmHg") else null
                Cmd.HRV -> (if (v > 0) v else r.hrv).takeIf { it > 0 }
                    ?.let { JSONObject().put("value", it).put("unit", "ms") }
                Cmd.STRESS -> (if (v > 0) v else r.stress).takeIf { it > 0 }
                    ?.let { JSONObject().put("value", it).put("unit", "score") }
                else -> null
            } ?: run { emptyResponses++; return }

            best = values
            validCount++
            if (cmd == Cmd.HR) {
                onLive("${values.optInt("value")} bpm")
                // Le cœur envoie une valeur par seconde : on termine après 6 valeurs valides
                if (validCount >= 6) finish(Outcome.Ok(values))
            } else {
                // Les autres mesures : on attend 2,5 s que la valeur se stabilise
                mainHandler.removeCallbacks(settle)
                mainHandler.postDelayed(settle, 2500)
            }
        }

        private fun onAll(r: StopHeartRateRsp) {
            if (done) return
            gotResponse()
            if (r.errCode.toInt() != 0) {
                val b = best
                finish(if (b != null) Outcome.Ok(b) else Outcome.Fail(Err.RING_REMOVED))
                return
            }
            val hr = if (r.heart > 0) r.heart else r.value
            if (hr <= 0) { emptyResponses++; return }
            val o = JSONObject()
            o.put("hr", hr)
            if (r.rri > 0) o.put("rri", r.rri)
            if (r.bloodOxygen > 0) o.put("spo2", r.bloodOxygen)
            if (r.hrv > 0) o.put("hrv", r.hrv)
            if (r.stress > 0) o.put("stress", r.stress)
            tempC(r.temperature)?.let { o.put("temp", it) }
            if (r.sbp > 0 && r.dbp > 0) { o.put("sbp", r.sbp); o.put("dbp", r.dbp) }
            best = o
            onLive("$hr bpm")
            mainHandler.removeCallbacks(settle)
            mainHandler.postDelayed(settle, 4000)
        }

        fun finish(outcome: Outcome) {
            if (done) return
            done = true
            mainHandler.removeCallbacks(timeout)
            mainHandler.removeCallbacks(settle)
            mainHandler.removeCallbacks(idleEnd)
            stopOnRing()
            if (session === this) session = null
            val checked = if (outcome is Outcome.Ok && !isValid(cmd, outcome.values))
                Outcome.Fail(Err.INVALID_VALUE) else outcome
            if (cont.isActive) cont.resume(checked)
        }

        private fun stopOnRing() {
            val bom = BleOperateManager.getInstance()
            try {
                when (cmd) {
                    Cmd.HR -> bom.manualModeHeart(null, true)
                    Cmd.SPO2 -> bom.manualModeSpO2(null, true)
                    Cmd.TEMP -> bom.manualTemperature(null, true)
                    Cmd.BP -> bom.manualModeBP(null, true)
                    Cmd.HRV -> bom.manualModeHrv(null, true)
                    Cmd.STRESS -> bom.manualModePressure(null, true)
                    Cmd.ALL -> bom.oneClickMeasurement(null, true)
                    else -> {}
                }
            } catch (e: Exception) {
                Log.w(TAG, "stop $cmd", e)
            }
        }
    }

    // ------------------------------------------------------------------ conversions / contrôles

    /**
     * La bague ne renvoie pas toujours la température à la même échelle :
     * 365 → 36.5 °C, 3650 → 36.5 °C, 165 → (165+200)/10 = 36.5 °C (format du SDK).
     */
    fun tempC(raw: Int): Double? {
        val c = when (raw) {
            in 300..450 -> raw / 10.0
            in 3000..4500 -> raw / 100.0
            in 100..250 -> (raw + 200) / 10.0
            in 30..45 -> raw.toDouble()
            else -> return null
        }
        return Math.round(c * 10) / 10.0
    }

    /** Refuse les valeurs aberrantes (bague mal portée, erreur capteur). */
    fun isValid(cmd: Cmd, v: JSONObject): Boolean = when (cmd) {
        Cmd.HR -> v.optInt("value") in 30..220
        Cmd.SPO2 -> v.optInt("value") in 70..100
        Cmd.TEMP -> v.optDouble("value", 0.0) in 30.0..43.0
        Cmd.BP -> v.optInt("sbp") in 70..230 && v.optInt("dbp") in 40..150
        Cmd.HRV -> v.optInt("value") in 1..300
        Cmd.STRESS -> v.optInt("value") in 1..100
        Cmd.ALL -> v.optInt("hr") in 30..220
        else -> true
    }
}
