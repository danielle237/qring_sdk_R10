package com.eis.qringmqtt.mqtt

import com.eis.qringmqtt.BuildConfig

/**
 * APK RHM V0.1 — identité FIXE de la gateway (cahier des charges V0.1).
 * Les valeurs viennent d'un seul endroit : app/build.gradle (variantes rhmDm100 / rhmDm80).
 * Le numéro (AND-DM100-0001, -0002…) s'incrémente à chaque compilation. Aucun écran pour les modifier.
 * Variante « classic » (TV) : RHM_ONLY = false, rien ne change.
 */
object RhmIdentity {
    val RHM_ONLY: Boolean = BuildConfig.RHM_ONLY
    val CLIENT_CODE: String = BuildConfig.RHM_CLIENT_CODE
    val SITE_CODE: String = BuildConfig.RHM_SITE_CODE
    val GATEWAY_ID: String = BuildConfig.RHM_GATEWAY_ID
    const val GATEWAY_TYPE = "android"
    val DEVICE_MODEL: String = BuildConfig.RHM_DEVICE_MODEL

    /** rhm/CSTOCK/SSTOCK/AND-DM100-0001 */
    val BASE: String get() = "rhm/$CLIENT_CODE/$SITE_CODE/$GATEWAY_ID"
}
