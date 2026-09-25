package com.eis.qringmqtt.ble

import com.oudmon.ble.base.bean.SleepDisplay
import com.oudmon.ble.base.communication.CommandHandle
import com.oudmon.ble.base.communication.Constants
import com.oudmon.ble.base.communication.ICommandResponse
import com.oudmon.ble.base.communication.IIntervalBloodOxygenCallback
import com.oudmon.ble.base.communication.ILargeDataLaunchSleepResponse
import com.oudmon.ble.base.communication.ILargeDataSleepResponse
import com.oudmon.ble.base.communication.LargeDataHandler
import com.oudmon.ble.base.communication.bigData.IIntervalTemperatureCallback
import com.oudmon.ble.base.communication.bigData.ILargeSettingForLongDataResponse
import com.oudmon.ble.base.communication.bigData.IntervalBloodOxygenEntity
import com.oudmon.ble.base.communication.bigData.bean.IntervalTemperatureEntity
import com.oudmon.ble.base.communication.entity.BleStepDetails
import com.oudmon.ble.base.communication.entity.BleStepTotal
import com.oudmon.ble.base.communication.req.HRVReq
import com.oudmon.ble.base.communication.req.PressureReq
import com.oudmon.ble.base.communication.req.ReadDetailSportDataReq
import com.oudmon.ble.base.communication.req.ReadHeartRateReq
import com.oudmon.ble.base.communication.req.ReadTotalSportDataReq
import com.oudmon.ble.base.communication.req.SimpleKeyReq
import com.oudmon.ble.base.communication.rsp.HRVRsp
import com.oudmon.ble.base.communication.rsp.LongSitResp
import com.oudmon.ble.base.communication.rsp.PressureRsp
import com.oudmon.ble.base.communication.rsp.ReadDetailSportDataRsp
import com.oudmon.ble.base.communication.rsp.ReadHeartRateRsp
import com.oudmon.ble.base.communication.rsp.SleepNewProtoResp
import com.oudmon.ble.base.communication.rsp.TodaySportDataRsp
import com.oudmon.ble.base.communication.rsp.TotalSportDataRsp
import com.oudmon.ble.base.communication.sport.BaseCallback
import com.oudmon.ble.base.communication.sport.SportPlusEntity
import com.oudmon.ble.base.communication.sport.SportPlusHandle
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject
import java.util.TimeZone

/**
 * Récupération des données enregistrées dans la mémoire de la bague :
 * pas, sommeil, sédentarité, entraînements, historique automatique.
 * Chaque fonction renvoie un JSON prêt à publier, ou null si la bague ne répond pas.
 */
object Syncer {

    // ------------------------------------------------------------------ pas / distance / calories

    suspend fun steps(day: Int): JSONObject? {
        val total: BleStepTotal? = if (day == 0) {
            awaitCallback<TodaySportDataRsp?>(8000) { resume ->
                CommandHandle.getInstance().executeReqCmd(
                    SimpleKeyReq(Constants.CMD_GET_STEP_TODAY),
                    ICommandResponse<TodaySportDataRsp> { resume(it) })
            }?.sportTotal
        } else {
            awaitCallback<TotalSportDataRsp?>(8000) { resume ->
                CommandHandle.getInstance().executeReqCmd(
                    ReadTotalSportDataReq(day),
                    ICommandResponse<TotalSportDataRsp> { resume(it) })
            }?.bleStepTotal
        }

        // Détail par tranche de 15 min (96 points) → regroupé par heure
        val details = ArrayList<BleStepDetails>()
        collect(6000, 1500) { add, _ ->
            CommandHandle.getInstance().executeReqCmd(
                ReadDetailSportDataReq(day, 0, 95),
                ICommandResponse<ReadDetailSportDataRsp> { r ->
                    r.bleStepDetailses?.let { list -> mainHandler.post { details.addAll(list); add() } }
                })
        }

        if (total == null && details.isEmpty()) return null
        val hourly = IntArray(24)
        details.forEach { d ->
            val h = (d.timeIndex / 4).coerceIn(0, 23)
            hourly[h] += d.walkSteps
        }
        return JSONObject().apply {
            put("day", day)
            if (total != null) {
                put("steps", total.totalSteps)
                put("runningSteps", total.runningSteps)
                put("distance", total.walkDistance)          // mètres
                put("calories", total.calorie)
                put("activeSeconds", total.sportDuration)
            } else {
                put("steps", hourly.sum())
                put("distance", details.sumOf { it.distance })
                put("calories", details.sumOf { it.calorie })
            }
            put("hourly", JSONArray(hourly.toList()))
        }
    }

    // ------------------------------------------------------------------ sommeil

    suspend fun sleep(day: Int): JSONObject? {
        var display: SleepDisplay? = null
        var proto: SleepNewProtoResp? = null
        collect(12000, 2500) { add, _ ->
            LargeDataHandler.getInstance().syncSleepList(day,
                ILargeDataSleepResponse { d -> mainHandler.post { if (d != null) { display = d; add() } } },
                ILargeDataLaunchSleepResponse { p -> mainHandler.post { if (p != null) { proto = p; add() } } }
            )
        }
        val d = display
        val p = proto
        if (d == null && p == null) return null

        val o = JSONObject().put("day", day)
        if (d != null) {
            o.put("start", d.sleepTime)
            o.put("end", d.wakeTime)
            o.put("totalSeconds", d.totalSleepDuration)
            o.put("deepSeconds", d.deepSleepDuration)
            o.put("lightSeconds", d.shallowSleepDuration)
            o.put("remSeconds", d.rapidDuration)
            o.put("awakeSeconds", d.awakeDuration)
            o.put("wakeCount", d.wakingCount)
            val phases = JSONArray()
            d.list?.forEach { b ->
                phases.put(JSONObject().put("start", b.sleepStart).put("end", b.sleepEnd).put("type", phaseName(b.type)))
            }
            o.put("phases", phases)
        }
        if (p != null) {
            // Nouveau protocole : liste de (durée en minutes, type)
            o.put("protoStart", p.st)
            o.put("protoEnd", p.et)
            val seq = JSONArray()
            var deep = 0; var light = 0; var awake = 0; var rem = 0
            p.list?.forEach { b ->
                seq.put(JSONObject().put("minutes", b.d).put("type", phaseName(b.t)))
                when (b.t) { 1 -> deep += b.d; 2 -> light += b.d; 3 -> awake += b.d; 4 -> rem += b.d }
            }
            o.put("sequence", seq)
            if (d == null) {
                o.put("totalSeconds", (deep + light + rem) * 60)
                o.put("deepSeconds", deep * 60)
                o.put("lightSeconds", light * 60)
                o.put("remSeconds", rem * 60)
                o.put("awakeSeconds", awake * 60)
            }
            if (p.isLunchBreak) o.put("nap", JSONObject().put("start", p.lunchSt).put("end", p.lunchEt))
        }
        return o
    }

    private fun phaseName(t: Int) = when (t) {
        1 -> "deep"; 2 -> "light"; 3 -> "awake"; 4 -> "rem"; 5 -> "not_worn"; else -> "unknown"
    }

    // ------------------------------------------------------------------ sédentarité

    suspend fun sedentary(day: Int): JSONObject? {
        val rsp = awaitCallback<LongSitResp?>(10000) { resume ->
            LargeDataHandler.getInstance().syncLongSitList(day,
                ILargeSettingForLongDataResponse { resume(it) })
        } ?: return null
        val seq = JSONArray()
        var still = 0; var alert = 0; var moving = 0
        rsp.list?.forEach { b ->
            val type = when (b.t) { 0 -> "still"; 1 -> "sedentary_alert"; 2 -> "moving"; else -> "unknown" }
            seq.put(JSONObject().put("minutes", b.d).put("type", type))
            when (b.t) { 0 -> still += b.d; 1 -> alert += b.d; 2 -> moving += b.d }
        }
        return JSONObject()
            .put("day", day)
            .put("stillMinutes", still)
            .put("sedentaryMinutes", alert)
            .put("movingMinutes", moving)
            .put("sequence", seq)
    }

    // ------------------------------------------------------------------ entraînements

    suspend fun workouts(): JSONObject? {
        val list = awaitCallback<List<SportPlusEntity>?>(20000) { resume ->
            val h = SportPlusHandle()
            h.timeFormat = "yyyy-MM-dd HH:mm"
            h.syncSportPlus(BaseCallback<List<SportPlusEntity>> { _, data -> resume(data ?: emptyList()) })
            h.cmdSummary(0)
        } ?: return null
        val arr = JSONArray()
        list.forEach { e ->
            arr.put(JSONObject().apply {
                put("sportType", e.mSportType)
                put("start", e.mStartTime)
                put("startText", e.trainingStartTime ?: "")
                put("durationSeconds", e.mDuration)
                put("distance", e.mDistance)
                put("calories", e.mCalories.toDouble())
                put("steps", e.steps)
                put("hrAvg", e.mRateAvg)
                put("hrMin", e.mRateMin)
                put("hrMax", e.mRateMax)
            })
        }
        return JSONObject().put("count", arr.length()).put("workouts", arr)
    }

    // ------------------------------------------------------------------ historique automatique

    /** Mesures faites seules par la bague dans la journée (cœur, stress, HRV, SpO2, température). */
    suspend fun history(day: Int): JSONObject {
        val o = JSONObject().put("day", day)

        // Cœur : un point toutes les 5 minutes
        val tz = (TimeZone.getDefault().getOffset(System.currentTimeMillis()) / 1000L)
        val t = nowSec() + tz - day * 86400L
        var hrArr: ByteArray? = null
        collect(8000, 1500) { add, _ ->
            CommandHandle.getInstance().executeReqCmd(ReadHeartRateReq(t),
                ICommandResponse<ReadHeartRateRsp> { r ->
                    mainHandler.post {
                        val a = r.getmHeartRateArray()
                        if (a != null && a.isNotEmpty()) { hrArr = a; add() }
                    }
                })
        }
        hrArr?.let { o.put("hr", series(it, 5)) }
        delay(300)

        // Stress : un point toutes les 30 minutes
        val stress = awaitCallback<PressureRsp?>(8000) { resume ->
            CommandHandle.getInstance().executeReqCmd(PressureReq(day.toByte()),
                ICommandResponse<PressureRsp> { resume(it) })
        }
        stress?.pressureArray?.let { o.put("stress", series(it, if (stress.range > 0) stress.range else 30)) }
        delay(300)

        // HRV : un point toutes les 30 minutes
        val hrv = awaitCallback<HRVRsp?>(8000) { resume ->
            CommandHandle.getInstance().executeReqCmd(HRVReq(day.toByte()),
                ICommandResponse<HRVRsp> { resume(it) })
        }
        hrv?.hrvArray?.let { o.put("hrv", series(it, if (hrv.range > 0) hrv.range else 30)) }
        delay(300)

        // SpO2 par intervalle
        val spo2 = awaitCallback<IntervalBloodOxygenEntity?>(10000) { resume ->
            LargeDataHandler.getInstance().syncIntervalBloodOxygenWithCallback(day,
                IIntervalBloodOxygenCallback { resume(it) })
        }
        spo2?.array?.let { list ->
            val step = if (spo2.interval > 0) spo2.interval else 1
            o.put("spo2", seriesInts(list.map { it ?: 0 }, step))
        }
        delay(300)

        // Température par intervalle
        val temp = awaitCallback<IntervalTemperatureEntity?>(10000) { resume ->
            LargeDataHandler.getInstance().syncIntervalTemperatureWithCallback(day,
                IIntervalTemperatureCallback { resume(it) })
        }
        temp?.array?.let { list ->
            val step = if (temp.interval > 0) temp.interval else 1
            val arr = JSONArray()
            list.forEachIndexed { i, v ->
                if (v != null && v > 0f) arr.put(JSONObject().put("minute", i * step).put("value", v.toDouble()))
            }
            o.put("temp", arr)
        }
        return o
    }

    /** Convertit un tableau d'octets (un point toutes les [stepMin] minutes) en [{minute, value}]. */
    private fun series(bytes: ByteArray, stepMin: Int): JSONArray {
        val arr = JSONArray()
        bytes.forEachIndexed { i, b ->
            val v = b.toInt() and 0xFF
            if (v > 0) arr.put(JSONObject().put("minute", i * stepMin).put("value", v))
        }
        return arr
    }

    private fun seriesInts(values: List<Int>, stepMin: Int): JSONArray {
        val arr = JSONArray()
        values.forEachIndexed { i, v -> if (v > 0) arr.put(JSONObject().put("minute", i * stepMin).put("value", v)) }
        return arr
    }

    /**
     * Pour les réponses envoyées en plusieurs paquets : on attend le premier paquet
     * (au plus [firstTimeoutMs]), puis on laisse [idleMs] aux paquets suivants.
     */
    private suspend fun collect(
        firstTimeoutMs: Long,
        idleMs: Long,
        start: (add: () -> Unit, finish: () -> Unit) -> Unit
    ) {
        var last = 0L
        var received = false
        try {
            start({ received = true; last = System.currentTimeMillis() }, {})
        } catch (_: Exception) {
            return
        }
        val begin = System.currentTimeMillis()
        while (true) {
            delay(200)
            val now = System.currentTimeMillis()
            if (!received && now - begin > firstTimeoutMs) return
            if (received && now - last > idleMs) return
        }
    }
}
