package com.eis.qringmqtt.data

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.Locale

/** Langues disponibles. Changement par Réglages ou par MQTT {"cmd":"lang","value":"ar"} (permanent). */
enum class Lang(val code: String, val label: String, val rtl: Boolean) {
    FR("fr", "Français", false),
    EN("en", "English", false),
    AR("ar", "العربية", true);

    companion object {
        fun from(code: String?): Lang? = values().firstOrNull { it.code.equals(code?.trim(), ignoreCase = true) }
    }
}

object I18n {
    /** Lu par l'interface : un changement redessine tout l'écran. */
    var lang by mutableStateOf(Lang.FR)

    /** Appareil TV (true) ou téléphone : « via TV » / « via téléphone ». Défini au démarrage (App). */
    var isTv: Boolean = true

    val locale: Locale get() = Locale(lang.code)
}

/** Traduction : tr("home.reconnect_in", 10) */
fun tr(key: String, vararg args: Any?): String {
    val row = S[key] ?: return key
    val s = when (I18n.lang) { Lang.FR -> row[0]; Lang.EN -> row[1]; Lang.AR -> row[2] }
    return if (args.isEmpty()) s else try { String.format(Locale.ROOT, s, *args) } catch (_: Exception) { s }
}

/** key → [français, anglais, arabe] */
private val S: Map<String, Array<String>> = mapOf(
    // ---------------- onglets
    "tab.home" to arrayOf("Accueil", "Home", "الرئيسية"),
    "tab.activity" to arrayOf("Activité", "Activity", "النشاط"),
    "tab.history" to arrayOf("Historique", "History", "السجل"),
    "tab.journal" to arrayOf("Journal", "Log", "سجل الرسائل"),
    "tab.settings" to arrayOf("Réglages", "Settings", "الإعدادات"),
    "tab.scan" to arrayOf("Scanner", "Scan", "البحث"),
    "tab.status" to arrayOf("État bague", "Ring status", "حالة الخاتم"),
    "nav.to_check" to arrayOf("à vérifier", "to check", "للتحقق"),

    // ---------------- états
    "ring.no_ring" to arrayOf("Aucune bague associée", "No ring paired", "لا يوجد خاتم مرتبط"),
    "ring.connecting" to arrayOf("Connexion…", "Connecting…", "جارٍ الاتصال…"),
    "ring.connected" to arrayOf("Connectée", "Connected", "متصل"),
    "ring.disconnected" to arrayOf("Hors portée", "Out of range", "خارج النطاق"),
    "ring.bluetooth_off" to arrayOf("Bluetooth désactivé", "Bluetooth off", "البلوتوث مغلق"),
    "broker.offline" to arrayOf("Hors ligne", "Offline", "غير متصل"),
    "broker.connecting" to arrayOf("Connexion…", "Connecting…", "جارٍ الاتصال…"),
    "broker.online" to arrayOf("En ligne", "Online", "متصل"),
    "lbl.ring" to arrayOf("Bague", "Ring", "الخاتم"),
    "lbl.broker" to arrayOf("Broker MQTT", "MQTT broker", "خادم MQTT"),

    // ---------------- mesures / commandes
    "m.hr" to arrayOf("Fréquence cardiaque", "Heart rate", "نبض القلب"),
    "m.spo2" to arrayOf("SpO2", "SpO2", "أكسجين الدم"),
    "m.temp" to arrayOf("Température", "Temperature", "الحرارة"),
    "m.bp" to arrayOf("Tension", "Blood pressure", "ضغط الدم"),
    "m.hrv" to arrayOf("HRV", "HRV", "تقلب النبض"),
    "m.stress" to arrayOf("Stress", "Stress", "التوتر"),
    "m.all" to arrayOf("Tout mesurer", "Measure all", "قياس الكل"),
    "m.steps" to arrayOf("Pas", "Steps", "الخطوات"),
    "m.sleep" to arrayOf("Sommeil", "Sleep", "النوم"),
    "m.sedentary" to arrayOf("Sédentarité", "Sedentary", "الخمول"),
    "m.workouts" to arrayOf("Entraînements", "Workouts", "التمارين"),
    "m.history" to arrayOf("Historique", "History", "السجل"),
    "m.battery" to arrayOf("Batterie", "Battery", "البطارية"),
    "m.info" to arrayOf("Infos bague", "Ring info", "معلومات الخاتم"),
    "m.ping" to arrayOf("Ping", "Ping", "Ping"),
    "m.cancel" to arrayOf("Annuler", "Cancel", "إلغاء"),
    "m.bind" to arrayOf("Associer", "Pair", "ربط"),
    "m.unbind" to arrayOf("Dissocier", "Unpair", "فك الارتباط"),
    "m.scan" to arrayOf("Scan", "Scan", "بحث"),
    "m.lang" to arrayOf("Langue", "Language", "اللغة"),

    // ---------------- erreurs
    "err.ring_disconnected" to arrayOf("Bague hors portée", "Ring out of range", "الخاتم خارج النطاق"),
    "err.ring_removed" to arrayOf("Bague retirée", "Ring removed", "الخاتم غير مرتدى"),
    "err.timeout" to arrayOf("Pas de résultat", "No result", "لا توجد نتيجة"),
    "err.measure_failed" to arrayOf("Mesure échouée", "Measurement failed", "فشل القياس"),
    "err.not_supported" to arrayOf("Non supporté par cette bague", "Not supported by this ring", "غير مدعوم في هذا الخاتم"),
    "err.busy" to arrayOf("Bague occupée", "Ring busy", "الخاتم مشغول"),
    "err.invalid_value" to arrayOf("Valeur incohérente", "Invalid value", "قيمة غير صالحة"),
    "err.cancelled" to arrayOf("Mesure annulée", "Measurement cancelled", "تم إلغاء القياس"),
    "err.no_data" to arrayOf("Aucune donnée", "No data", "لا توجد بيانات"),
    "err.not_found" to arrayOf("Bague introuvable", "Ring not found", "لم يتم العثور على الخاتم"),
    "err.bluetooth_off" to arrayOf("Bluetooth désactivé", "Bluetooth off", "البلوتوث مغلق"),
    "err.unknown_command" to arrayOf("Commande inconnue", "Unknown command", "أمر غير معروف"),
    "err.bad_request" to arrayOf("Paramètre manquant", "Missing parameter", "معامل مفقود"),

    // ---------------- accueil
    "home.wear_title" to arrayOf("Bague retirée", "Ring removed", "الخاتم غير مرتدى"),
    "home.wear_text" to arrayOf(
        "Veuillez porter la bague, puis relancez la mesure",
        "Please wear the ring, then start the measurement again",
        "يرجى ارتداء الخاتم ثم إعادة القياس"
    ),
    "home.disc_title" to arrayOf("Bague hors portée", "Ring out of range", "الخاتم خارج النطاق"),
    "home.bt_off_title" to arrayOf("Bluetooth désactivé", "Bluetooth off", "البلوتوث مغلق"),
    "home.bt_off_text" to arrayOf("Activez le Bluetooth de l'appareil", "Turn on the device's Bluetooth", "فعّل البلوتوث في الجهاز"),
    "home.reconnect_in" to arrayOf("Reconnexion automatique dans %d s", "Reconnecting automatically in %d s", "إعادة الاتصال تلقائيًا خلال %d ث"),
    "home.reconnecting" to arrayOf("Reconnexion en cours…", "Reconnecting…", "جارٍ إعادة الاتصال…"),
    "home.no_ring" to arrayOf("Aucune bague", "No ring", "لا يوجد خاتم"),
    "home.press_scan" to arrayOf("Appuyez sur Scanner pour associer une bague", "Press Scan to pair a ring", "اضغط على بحث لربط خاتم"),
    "home.service_active" to arrayOf("Service actif en arrière-plan", "Background service running", "الخدمة تعمل في الخلفية"),
    "home.charging" to arrayOf("en charge", "charging", "قيد الشحن"),
    "home.measuring" to arrayOf("Mesure…", "Measuring…", "جارٍ القياس…"),
    "home.syncing" to arrayOf("Synchronisation…", "Syncing…", "جارٍ المزامنة…"),
    "home.queued" to arrayOf("En attente…", "Waiting…", "في الانتظار…"),
    "home.tap_measure" to arrayOf("Appuyez pour mesurer", "Press to measure", "اضغط للقياس"),
    "home.tap_sync" to arrayOf("Appuyez pour synchroniser", "Press to sync", "اضغط للمزامنة"),
    "home.all_running" to arrayOf("Mesure complète en cours…", "Full measurement running…", "جارٍ القياس الكامل…"),
    "home.rri" to arrayOf("RRI %d ms", "RRI %d ms", "RRI %d مل.ث"),
    "home.deep" to arrayOf("profond %s", "deep %s", "عميق %s"),
    "home.still" to arrayOf("immobile", "still", "ساكن"),
    "home.sessions" to arrayOf("séances", "sessions", "حصص"),
    "btn.reconnect" to arrayOf("Reconnecter", "Reconnect", "إعادة الاتصال"),
    "btn.scan" to arrayOf("Scanner", "Scan", "بحث"),
    "btn.cancel" to arrayOf("Annuler", "Cancel", "إلغاء"),
    "btn.unbind" to arrayOf("Dissocier", "Unpair", "فك الارتباط"),
    "btn.hide" to arrayOf("Masquer", "Hide", "إخفاء"),
    "btn.retry" to arrayOf("Relancer", "Measure again", "إعادة القياس"),
    "btn.close" to arrayOf("Fermer", "Close", "إغلاق"),
    "btn.back" to arrayOf("Retour", "Back", "رجوع"),

    // ---------------- temps / source
    "t.now" to arrayOf("à l'instant", "just now", "الآن"),
    "t.min" to arrayOf("il y a %d min", "%d min ago", "منذ %d د"),
    "t.h" to arrayOf("il y a %d h", "%d h ago", "منذ %d س"),
    "t.yesterday" to arrayOf("hier", "yesterday", "أمس"),
    "src.mqtt" to arrayOf("via Serveur", "on Server", "عن بُعد"),
    "src.manual" to arrayOf("via G-RHM", "on G-RHM", "عبر التلفاز"),
    "src.manual_phone" to arrayOf("via téléphone", "on phone", "عبر الهاتف"),
    "src.phone_p" to arrayOf("prise", "taken", "مأخوذ"),
    "src.phone_r" to arrayOf("actualisée", "refreshed", "محدَّث"),
    "src.by" to arrayOf("par %s", "by %s", "بواسطة %s"),
    "src.auto" to arrayOf("auto", "auto", "تلقائي"),

    // ---------------- activité
    "act.sync" to arrayOf("Synchroniser l'activité", "Sync activity", "مزامنة النشاط"),
    "act.syncing" to arrayOf("Synchronisation : %s…", "Syncing: %s…", "جارٍ المزامنة: %s…"),
    "act.distance" to arrayOf("Distance", "Distance", "المسافة"),
    "act.calories" to arrayOf("Calories", "Calories", "السعرات"),
    "act.active" to arrayOf("Temps actif", "Active time", "وقت النشاط"),
    "act.goal" to arrayOf("/ %s pas", "/ %s steps", "/ %s خطوة"),
    "act.per_hour" to arrayOf("Pas par heure", "Steps per hour", "الخطوات في الساعة"),
    "act.deep" to arrayOf("Profond", "Deep", "عميق"),
    "act.light" to arrayOf("Léger", "Light", "خفيف"),
    "act.rem" to arrayOf("REM", "REM", "REM"),
    "act.awake" to arrayOf("Éveil", "Awake", "يقظة"),
    "act.no_data" to arrayOf("Aucune donnée. Appuyez sur Synchroniser.", "No data. Press Sync.", "لا توجد بيانات. اضغط مزامنة."),
    "act.still" to arrayOf("Immobile", "Still", "ساكن"),
    "act.alerts" to arrayOf("Alertes", "Alerts", "تنبيهات"),
    "act.moving" to arrayOf("En mouvement", "Moving", "في حركة"),
    "act.no_workouts" to arrayOf("Aucun entraînement enregistré.", "No workout recorded.", "لا توجد تمارين مسجلة."),
    "act.session" to arrayOf("Séance", "Session", "حصة"),
    "gen.no_data" to arrayOf("Aucune donnée.", "No data.", "لا توجد بيانات."),

    // ---------------- historique
    "hist.day" to arrayOf("Jour", "Day", "يوم"),
    "hist.7d" to arrayOf("7 jours", "7 days", "7 أيام"),
    "hist.30d" to arrayOf("30 jours", "30 days", "30 يومًا"),
    "hist.import" to arrayOf("Importer de la bague", "Import from ring", "استيراد من الخاتم"),
    "hist.importing" to arrayOf("Import…", "Importing…", "جارٍ الاستيراد…"),
    "hist.stats" to arrayOf("moy. %s · min %s · max %s", "avg %s · min %s · max %s", "المتوسط %s · الأدنى %s · الأعلى %s"),
    "hist.none" to arrayOf("Aucune mesure sur cette période.", "No measurement in this period.", "لا توجد قياسات في هذه الفترة."),
    "hist.measures" to arrayOf("Mesures", "Measurements", "القياسات"),
    "hist.all_rings" to arrayOf("Toutes les bagues", "All rings", "كل الخواتم"),
    "hist.current" to arrayOf("actuelle", "current", "الحالي"),

    // ---------------- journal
    "log.title" to arrayOf("Journal MQTT", "MQTT log", "سجل MQTT"),
    "log.all" to arrayOf("Tout", "All", "الكل"),
    "log.cmds" to arrayOf("Commandes", "Commands", "الأوامر"),
    "log.results" to arrayOf("Résultats", "Results", "النتائج"),
    "log.errors" to arrayOf("Erreurs", "Errors", "الأخطاء"),
    "log.clear" to arrayOf("Vider", "Clear", "مسح"),
    "log.pending" to arrayOf("En attente d'envoi (hors ligne)", "Waiting to send (offline)", "في انتظار الإرسال (غير متصل)"),
    "log.empty" to arrayOf("Aucun message pour l'instant.", "No message yet.", "لا توجد رسائل بعد."),
    "kind.in" to arrayOf("⬇ CMD", "⬇ CMD", "⬇ أمر"),
    "kind.out" to arrayOf("⬆ RÉSULTAT", "⬆ RESULT", "⬆ نتيجة"),
    "kind.status" to arrayOf("⬆ STATUT", "⬆ STATUS", "⬆ الحالة"),
    "kind.measuring" to arrayOf("⬆ MESURE", "⬆ MEASURING", "⬆ قياس"),
    "kind.error" to arrayOf("⬆ ERREUR", "⬆ ERROR", "⬆ خطأ"),
    "kind.info" to arrayOf("ℹ INFO", "ℹ INFO", "ℹ معلومة"),

    // ---------------- PIN
    "pin.enter" to arrayOf("Entrez le code PIN", "Enter PIN code", "أدخل الرمز السري"),
    "pin.wrong" to arrayOf("Code incorrect", "Wrong code", "رمز خاطئ"),
    "pin.blocked" to arrayOf("Trop d'essais. Réessayez dans %d s", "Too many attempts. Retry in %d s", "محاولات كثيرة. أعد المحاولة بعد %d ث"),

    // ---------------- réglages
    "set.title" to arrayOf("Réglages", "Settings", "الإعدادات"),
    "set.language" to arrayOf("Langue", "Language", "اللغة"),
    "set.broker" to arrayOf("Broker MQTT", "MQTT broker", "خادم MQTT"),
    "set.host" to arrayOf("Hôte", "Host", "الخادم"),
    "set.port" to arrayOf("Port", "Port", "المنفذ"),
    "set.user" to arrayOf("Utilisateur", "User", "المستخدم"),
    "set.pass" to arrayOf("Mot de passe", "Password", "كلمة المرور"),
    "set.show" to arrayOf("Afficher", "Show", "إظهار"),
    "set.prefix" to arrayOf("Préfixe des topics", "Topic prefix", "بادئة المواضيع"),
    "set.gateway" to arrayOf("Nom du gateway (unique)", "Gateway name (unique)", "اسم البوابة (فريد)"),
    "set.topic" to arrayOf("Topic bague : %s", "Ring topic: %s", "موضوع الخاتم: %s"),
    "set.gw_topic" to arrayOf("Topic gateway : %s", "Gateway topic: %s", "موضوع البوابة: %s"),
    "set.save" to arrayOf("Enregistrer et reconnecter", "Save and reconnect", "حفظ وإعادة الاتصال"),
    "set.saved" to arrayOf("Réglages enregistrés", "Settings saved", "تم حفظ الإعدادات"),
    "set.ring" to arrayOf("Bague", "Ring", "الخاتم"),
    "set.name" to arrayOf("Nom", "Name", "الاسم"),
    "set.mac" to arrayOf("Adresse MAC", "MAC address", "عنوان MAC"),
    "set.model" to arrayOf("Modèle", "Model", "الطراز"),
    "set.fw" to arrayOf("Firmware", "Firmware", "البرنامج الثابت"),
    "set.hw" to arrayOf("Matériel", "Hardware", "العتاد"),
    "set.charging" to arrayOf("(en charge)", "(charging)", "(قيد الشحن)"),
    "set.supports" to arrayOf("Fonctions supportées", "Supported features", "الميزات المدعومة"),
    "set.change" to arrayOf("Changer de bague", "Change ring", "تغيير الخاتم"),
    "set.unbind" to arrayOf("Dissocier la bague", "Unpair ring", "فك ارتباط الخاتم"),
    "set.unbind_q" to arrayOf("Dissocier %s ?", "Unpair %s?", "فك ارتباط %s؟"),
    "set.unbind_text" to arrayOf(
        "La bague ne sera plus suivie par cet appareil. L'historique est conservé.",
        "The ring will no longer be followed by this device. History is kept.",
        "لن يتابع هذا الجهاز الخاتم بعد الآن. يتم الاحتفاظ بالسجل."
    ),
    "set.unbound" to arrayOf("Bague dissociée", "Ring unpaired", "تم فك ارتباط الخاتم"),
    "set.background" to arrayOf("Fonctionnement en arrière-plan", "Background operation", "العمل في الخلفية"),
    "set.batt_ok" to arrayOf("✓ Optimisation de batterie désactivée pour l'app", "✓ Battery optimization disabled for the app", "✓ تم تعطيل تحسين البطارية للتطبيق"),
    "set.batt_warn" to arrayOf("⚠ L'optimisation de batterie peut arrêter le service", "⚠ Battery optimization may stop the service", "⚠ قد يوقف تحسين البطارية الخدمة"),
    "set.allow_bg" to arrayOf("Autoriser l'arrière-plan", "Allow background", "السماح بالعمل في الخلفية"),
    "set.allow_autostart" to arrayOf("Autoriser le démarrage automatique", "Allow auto-start", "السماح بالتشغيل التلقائي"),
    "set.pin" to arrayOf("Code PIN", "PIN code", "الرمز السري"),
    "set.new_pin" to arrayOf("Nouveau code PIN (4 à 8 chiffres)", "New PIN (4 to 8 digits)", "رمز جديد (4 إلى 8 أرقام)"),
    "set.change_pin" to arrayOf("Changer le PIN", "Change PIN", "تغيير الرمز"),
    "set.lock" to arrayOf("Verrouiller", "Lock", "قفل"),
    "set.pin_changed" to arrayOf("Code PIN modifié", "PIN changed", "تم تغيير الرمز"),

    // ---------------- scan
    "scan.title" to arrayOf("Associer une bague", "Pair a ring", "ربط خاتم"),
    "scan.searching" to arrayOf("Recherche des bagues à proximité…", "Searching for nearby rings…", "جارٍ البحث عن الخواتم القريبة…"),
    "scan.bt_off" to arrayOf("Activez le Bluetooth puis relancez la recherche", "Turn on Bluetooth and search again", "فعّل البلوتوث ثم أعد البحث"),
    "scan.found" to arrayOf("%d appareil(s) trouvé(s) · ↻ pour relancer", "%d device(s) found · ↻ to search again", "تم العثور على %d جهاز · ↻ لإعادة البحث"),
    "scan.nearby" to arrayOf("Appareils à proximité", "Nearby devices", "الأجهزة القريبة"),
    "scan.current" to arrayOf("(actuelle)", "(current)", "(الحالي)"),

    // ---------------- TV / résultat
    "tv.server" to arrayOf("Mesure demandée par le serveur", "Measurement requested by the server", "قياس مطلوب من الخادم"),
    "tv.measuring" to arrayOf("Mesure en cours", "Measuring", "جارٍ القياس"),
    "tv.hold" to arrayOf("Gardez la bague au doigt et restez immobile", "Keep the ring on your finger and stay still", "أبقِ الخاتم في إصبعك وابقَ ساكنًا"),
    "tv.result" to arrayOf("Résultat", "Result", "النتيجة"),

    // ---------------- premier lancement
    "ob.welcome" to arrayOf("Bienvenue", "Welcome", "مرحبًا"),
    "ob.text" to arrayOf(
        "Pour mesurer en tâche de fond (même app fermée), l'application a besoin de quelques autorisations. Elles ne sont demandées qu'une seule fois.",
        "To measure in the background (even with the app closed), the app needs a few permissions. They are asked only once.",
        "للقياس في الخلفية (حتى مع إغلاق التطبيق)، يحتاج التطبيق إلى بعض الأذونات. تُطلب مرة واحدة فقط."
    ),
    "ob.s1" to arrayOf("Bluetooth, localisation et notifications", "Bluetooth, location and notifications", "البلوتوث والموقع والإشعارات"),
    "ob.s1t" to arrayOf("Pour trouver et rester connecté à la bague.", "To find the ring and stay connected.", "للعثور على الخاتم والبقاء متصلًا به."),
    "ob.s2" to arrayOf("Fonctionner en arrière-plan", "Run in the background", "العمل في الخلفية"),
    "ob.s2t" to arrayOf("Empêche Android d'arrêter le service.", "Prevents Android from stopping the service.", "يمنع أندرويد من إيقاف الخدمة."),
    "ob.s3" to arrayOf("Démarrage automatique", "Auto-start", "التشغيل التلقائي"),
    "ob.s3t" to arrayOf("Réglage du fabricant : activez Gateway RHM dans la liste.", "Manufacturer setting: enable Gateway RHM in the list.", "إعداد الشركة المصنعة: فعّل Gateway RHM في القائمة."),
    "ob.continue" to arrayOf("Continuer", "Continue", "متابعة"),
    "ob.required" to arrayOf("L'étape 1 est obligatoire.", "Step 1 is required.", "الخطوة 1 إلزامية."),
    "ob.allow" to arrayOf("Autoriser", "Allow", "سماح"),

    // ---------------- notification
    "n.title" to arrayOf("Gateway RHM actif", "Gateway RHM active", "Gateway RHM نشط"),
    "n.channel" to arrayOf("Service Gateway RHM", "Gateway RHM service", "خدمة Gateway RHM"),
    // ---- Bouton « État de la bague » (accueil)
    "st.button" to arrayOf("État de la bague", "Ring status", "حالة الخاتم"),
    "st.checking" to arrayOf("Vérification de la bague…", "Checking the ring…", "جارٍ فحص الخاتم…"),
    "st.request" to arrayOf("Demande envoyée à la bague…", "Request sent to the ring…", "تم إرسال الطلب إلى الخاتم…"),
    "st.worn" to arrayOf("Bague portée — vérifiée à %s", "Ring worn — checked at %s", "الخاتم ملبوس — تم التحقق في %s"),
    "st.recent" to arrayOf("Vérification récente réutilisée", "Recent check reused", "تمت إعادة استخدام تحقق حديث"),
    "st.measuring" to arrayOf("%s en cours · %d s / %d s", "%s measuring · %d s / %d s", "%s قيد القياس · %d ث / %d ث"),
    "st.follow" to arrayOf("Mesure %s déjà en cours : elle sert de vérification", "%s measurement already running: used as check", "قياس %s جارٍ: يُستخدم للتحقق"),
    "st.removed" to arrayOf("Bague retirée — veuillez porter la bague", "Ring removed — please wear the ring", "الخاتم منزوع — يرجى ارتداء الخاتم"),
    "st.out" to arrayOf("Bague hors portée", "Ring out of range", "الخاتم خارج النطاق"),
    "st.bt_off" to arrayOf("Bluetooth désactivé", "Bluetooth off", "البلوتوث مغلق"),
    "st.no_ring" to arrayOf("Aucune bague associée", "No ring paired", "لا يوجد خاتم مقترن"),
    "st.unconfirmed" to arrayOf("Pas de signal — port non confirmé", "No signal — wear not confirmed", "لا توجد إشارة — لم يتم تأكيد الارتداء"),
    "st.failed" to arrayOf("Vérification impossible : %s", "Check failed: %s", "تعذر التحقق: %s"),
    "home.battery_at" to arrayOf("dernière date de vérification %s", "read at %s", "قُرئت في %s"),
    // ---- État permanent de la bague (bandeau de l'accueil, carte du menu)
    "rs.no_ring" to arrayOf("Aucune bague", "No ring", "لا يوجد خاتم"),
    "rs.bt_off" to arrayOf("Bluetooth désactivé", "Bluetooth off", "البلوتوث مغلق"),
    "rs.connecting" to arrayOf("Connexion…", "Connecting…", "جارٍ الاتصال…"),
    "rs.out" to arrayOf("Hors portée", "Out of range", "خارج النطاق"),
    "rs.out_title" to arrayOf("Bague hors portée", "Ring out of range", "الخاتم خارج النطاق"),
    "rs.out_detail" to arrayOf("depuis %s · reconnexion automatique", "since %s · reconnecting automatically", "منذ %s · إعادة اتصال تلقائية"),
    "rs.checking" to arrayOf("Vérification…", "Checking…", "جارٍ التحقق…"),
    "rs.worn" to arrayOf("Portée", "Worn", "مرتدى"),
    "rs.worn_title" to arrayOf("Bague portée", "Ring worn", "الخاتم مرتدى"),
    "rs.checked_at" to arrayOf("Date de vérification à %s", "checked at %s", "تم التحقق في %s"),
    "rs.measured_at" to arrayOf("Mesure à %s", "Measured at %s", "قياس في %s"),
    "rs.removed_at" to arrayOf("détectée à %s", "detected at %s", "اكتُشف في %s"),
    "rs.since" to arrayOf("depuis %s", "since %s", "منذ %s"),
    "rs.removed" to arrayOf("Retirée", "Removed", "منزوع"),
    "rs.removed_title" to arrayOf("Bague retirée", "Ring removed", "الخاتم منزوع"),
    "rs.removed_detail" to arrayOf("détectée à %s · veuillez porter la bague", "detected at %s · please wear the ring", "اكتُشف في %s · يرجى ارتداء الخاتم"),
    "rs.unchecked" to arrayOf("Connectée", "Connected", "متصل"),
    "rs.unchecked_title" to arrayOf("Bague connectée", "Ring connected", "الخاتم متصل"),
    "rs.unchecked_detail" to arrayOf("appuyez sur Actualiser pour vérifier", "press Refresh to check", "اضغط تحديث للتحقق"),
    // ---- Bouton Actualiser
    "st.refresh" to arrayOf("Actualiser l'état de la bague", "Refresh ring status", "تحديث حالة الخاتم"),
    "st.refresh_in" to arrayOf("Actualiser dans %s", "Refresh in %s", "تحديث بعد %s"),
    "st.checking_btn" to arrayOf("Vérification… %d s / %d s", "Checking… %d s / %d s", "جارٍ التحقق… %d ث / %d ث"),
    // ---- Popups
    "pop.back_title" to arrayOf("Content de vous revoir !", "Welcome back!", "مرحبًا بعودتك!"),
    "pop.back_text" to arrayOf("Votre bague est de nouveau connectée.", "Your ring is connected again.", "خاتمك متصل مجددًا."),
    "pop.back_q" to arrayOf("On vérifie qu'elle est bien à votre doigt ?", "Shall we check it's on your finger?", "هل نتحقق من أنه في إصبعك؟"),
    "pop.back_yes" to arrayOf("Oui, vérifier", "Yes, check", "نعم، تحقق"),
    "pop.out_title" to arrayOf("Votre bague s'est éloignée", "Your ring is out of reach", "ابتعد خاتمك"),
    "pop.out_text_tv" to arrayOf("Rapprochez-vous de la Gateway RHM, elle se reconnectera toute seule.", "Move closer to the TV — it will reconnect automatically.", "اقترب من التلفاز، وسيعاد الاتصال تلقائيًا."),
    "pop.out_text_phone" to arrayOf("Rapprochez-vous du téléphone, elle se reconnectera toute seule.", "Move closer to the phone — it will reconnect automatically.", "اقترب من الهاتف، وسيعاد الاتصال تلقائيًا."),
    "pop.ok" to arrayOf("OK", "OK", "حسنًا"),
    "pop.recent_title" to arrayOf("Vous venez de faire une mesure", "A measurement was just taken", "تم إجراء قياس للتو"),
    "pop.recent_text" to arrayOf("L'état de la bague est déjà à jour.", "The ring status is already up to date.", "حالة الخاتم محدّثة بالفعل."),
    "pop.busy_title" to arrayOf("Mesure en cours", "Measurement in progress", "القياس جارٍ"),
    "pop.busy_text" to arrayOf("Veuillez patienter : la vérification de la bague sera lancée à la fin de la mesure en cours (%s).", "Please wait: the ring check will start when the current measurement ends (%s).", "يرجى الانتظار: سيبدأ فحص الخاتم عند انتهاء القياس الجاري (%s)."),
    "st.waiting" to arrayOf("En attente de la fin de la mesure…", "Waiting for the measurement to end…", "في انتظار انتهاء القياس…"),
    "lbl.broker_line" to arrayOf("Broker MQTT : %s", "MQTT broker: %s", "خادم MQTT: %s"),
    "pop.removed_title" to arrayOf("Oups, la bague n'est pas portée", "Oops, the ring isn't being worn", "عذرًا، الخاتم غير مرتدى"),
    "pop.removed_text" to arrayOf("Mettez-la au doigt pour que la mesure fonctionne.", "Put it on your finger so the measurement can work.", "ضعه في إصبعك ليعمل القياس."),
    "pop.removed_q" to arrayOf("On réessaie ?", "Try again?", "هل نعيد المحاولة؟"),
    "pop.retry" to arrayOf("Réessayer", "Try again", "إعادة المحاولة"),
    "btn.later" to arrayOf("Plus tard", "Later", "لاحقًا"),
    "n.starting" to arrayOf("Démarrage…", "Starting…", "جارٍ التشغيل…"),
    "n.ring_ok" to arrayOf("Bague connectée", "Ring connected", "الخاتم متصل"),
    "n.broker" to arrayOf("Broker %s", "Broker %s", "الخادم %s"),
    "n.measuring" to arrayOf("Mesure en cours : %s", "Measuring: %s", "جارٍ القياس: %s"),
    "n.cancel" to arrayOf("Annuler la mesure", "Cancel measurement", "إلغاء القياس")
)
