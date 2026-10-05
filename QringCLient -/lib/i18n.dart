// Traductions FR / EN / AR (même vocabulaire que l'app Gateway RHM).

String appLang = 'fr';

bool get isRtl => appLang == 'ar';

/// tr('rs.checked_at', ['12:51'])
String tr(String key, [List<Object?> args = const []]) {
  final row = _s[key];
  if (row == null) return key;
  var s = appLang == 'en' ? row[1] : appLang == 'ar' ? row[2] : row[0];
  for (final a in args) {
    s = s.replaceFirst('%s', '${a ?? ''}');
  }
  return s;
}

const Map<String, List<String>> _s = {
  // ------------------------------------------------ général
  'app.org': ['EHPAD de la Vie', 'EHPAD de la Vie', 'EHPAD de la Vie'],
  'app.sub': ['Suivi des bagues RHM', 'RHM ring monitoring', 'متابعة خواتم RHM'],
  'btn.ok': ['OK', 'OK', 'حسنًا'],
  'btn.cancel': ['Annuler', 'Cancel', 'إلغاء'],
  'btn.close': ['Fermer', 'Close', 'إغلاق'],
  'btn.retry': ['Réessayer', 'Try again', 'إعادة المحاولة'],
  'btn.save': ['Enregistrer', 'Save', 'حفظ'],
  'err.network': ['Serveur injoignable. Vérifiez la connexion internet.', 'Server unreachable. Check your internet connection.', 'تعذر الوصول إلى الخادم. تحقق من الاتصال.'],
  'live.on': ['en direct', 'live', 'مباشر'],
  'live.off': ['reconnexion…', 'reconnecting…', 'إعادة الاتصال…'],

  // ------------------------------------------------ connexion
  'login.user': ['Identifiant', 'Username', 'اسم المستخدم'],
  'login.pass': ['Mot de passe', 'Password', 'كلمة المرور'],
  'login.keep': ['Rester connecté', 'Stay signed in', 'البقاء متصلًا'],
  'login.go': ['Se connecter', 'Sign in', 'تسجيل الدخول'],
  'login.server': ['Adresse du serveur', 'Server address', 'عنوان الخادم'],
  'login.server_adv': ['Paramètres du serveur', 'Server settings', 'إعدادات الخادم'],
  'login.admin': ['Compte créé par l\'administrateur', 'Account created by the administrator', 'حساب أنشأه المسؤول'],

  // ------------------------------------------------ onglets
  'tab.rings': ['Bagues', 'Rings', 'الخواتم'],
  'tab.alerts': ['Alertes', 'Alerts', 'التنبيهات'],
  'tab.profile': ['Profil', 'Profile', 'الملف'],
  'rings.title': ['Mes bagues', 'My rings', 'خواتمي'],
  'rings.none': ['Aucune bague ne vous est affectée pour l\'instant.\nContactez l\'administrateur.', 'No ring is assigned to you yet.\nContact the administrator.', 'لا يوجد خاتم مخصص لك بعد.\nتواصل مع المسؤول.'],
  'rings.last_state': ['Dernier état constaté :', 'Last known state:', 'آخر حالة مسجلة:'],
  'rings.last_values': ['Dernières mesures constatées :', 'Latest readings:', 'آخر القياسات المسجلة:'],
  'rings.alerts_all': ['Alertes : toutes les bagues', 'Alerts: all rings', 'التنبيهات: كل الخواتم'],
  'rings.alerts_off_global': ['Alertes désactivées dans le Profil', 'Alerts turned off in Profile', 'التنبيهات معطلة في الملف'],

  // ------------------------------------------------ état de la bague
  'rs.gw_off': ['Gateway RHM hors ligne', 'Gateway RHM offline', 'بوابة RHM غير متصلة'],
  'rs.gw_off_why': ['Gateway RHM éteinte ou sans internet', 'Gateway RHM off or without internet', 'بوابة RHM مطفأة أو بلا إنترنت'],
  'rs.gw_on': ['📡 Gateway RHM en ligne', '📡 Gateway RHM online', '📡 بوابة RHM متصلة'],
  'rs.unbound_at': ['Dissociée à %s', 'Unpaired at %s', 'فُصل في %s'],
  'rs.removed_at': ['Retirée à %s · %s', 'Removed at %s · %s', 'نُزع في %s · %s'],
  'rs.a_worn': ['Bague associée · portée', 'Paired ring · worn', 'خاتم مرتبط · مرتدى'],
  'rs.a_removed': ['Bague associée · retirée', 'Paired ring · removed', 'خاتم مرتبط · منزوع'],
  'rs.a_out': ['Bague associée · hors portée', 'Paired ring · out of range', 'خاتم مرتبط · خارج النطاق'],
  'rs.a_connected': ['Bague associée · connectée', 'Paired ring · connected', 'خاتم مرتبط · متصل'],
  'rs.last_state': ['Dernier état connu · %s', 'Last known state · %s', 'آخر حالة معروفة · %s'],
  'rs.worn_at': ['Vérifiée à %s · %s', 'Checked at %s · %s', 'تم التحقق في %s · %s'],
  'rs.out_since': ['Hors portée depuis %s · %s', 'Out of range since %s · %s', 'خارج النطاق منذ %s · %s'],
  'rs.bound': ['Bague associée à la GATEWAY RHM', 'Ring paired with the GATEWAY RHM', 'الخاتم مرتبط ببوابة RHM'],
  'rs.gw_pill_on': ['GATEWAY RHM EN LIGNE', 'GATEWAY RHM ONLINE', 'بوابة RHM متصلة'],
  'rs.gw_pill_off': ['GATEWAY RHM HORS LIGNE', 'GATEWAY RHM OFFLINE', 'بوابة RHM غير متصلة'],
  'rs.unbound': ['Bague dissociée de la GATEWAY RHM', 'Ring unpaired from the GATEWAY RHM', 'الخاتم غير مرتبط ببوابة RHM'],
  'rs.out': ['Bague hors portée', 'Ring out of range', 'الخاتم خارج النطاق'],
  'rs.bt_off': ['Bluetooth de la Gateway RHM désactivé', 'Gateway RHM Bluetooth off', 'بلوتوث بوابة RHM مغلق'],
  'rs.no_ring': ['Aucune bague sur la Gateway RHM', 'No ring on the Gateway RHM', 'لا يوجد خاتم على بوابة RHM'],
  'rs.removed': ['Bague retirée', 'Ring removed', 'الخاتم منزوع'],
  'rs.worn': ['Bague portée', 'Ring worn', 'الخاتم مرتدى'],
  'rs.connected': ['Bague connectée', 'Ring connected', 'الخاتم متصل'],
  'rs.unknown': ['Aucune nouvelle de la Gateway RHM', 'No news from the Gateway RHM', 'لا أخبار من بوابة RHM'],
  'rs.measuring': ['Mesure %s en cours · %s s', '%s measuring · %s s', 'قياس %s جارٍ · %s ث'],
  'rs.tv': ['Gateway RHM : %s', 'Gateway RHM: %s', 'بوابة RHM: %s'],
  'rs.status_at': ['dernier statut %s', 'last status %s', 'آخر حالة %s'],

  // ------------------------------------------------ mesures
  'm.hr': ['Fréquence cardiaque', 'Heart rate', 'نبض القلب'],
  'm.spo2': ['SpO2', 'SpO2', 'أكسجين الدم'],
  'm.temp': ['Température', 'Temperature', 'الحرارة'],
  'm.bp': ['Tension', 'Blood pressure', 'ضغط الدم'],
  'm.hrv': ['HRV', 'HRV', 'تقلب النبض'],
  'm.stress': ['Stress', 'Stress', 'التوتر'],
  'm.steps': ['Pas', 'Steps', 'الخطوات'],
  'm.battery': ['Batterie', 'Battery', 'البطارية'],
  'btn.hr': ['HR', 'HR', 'النبض'],
  'btn.spo2': ['SpO2', 'SpO2', 'الأكسجين'],
  'btn.temp': ['T°', 'T°', 'الحرارة'],
  'btn.bp': ['Tension', 'BP', 'الضغط'],
  'btn.hrv': ['HRV', 'HRV', 'HRV'],
  'btn.stress': ['Stress', 'Stress', 'التوتر'],
  'btn.steps': ['Pas', 'Steps', 'الخطوات'],
  'btn.battery': ['Batterie', 'Battery', 'البطارية'],
  'ring.last': ['Dashboard des Dernières mesures', 'Latest readings', 'آخر القياسات'],
  'ring.launch': ['veuillez Cliquer sur un bouton ci-dessus pour  Lancer une mesure', 'Start a measurement', 'بدء قياس'],
  'ring.no_value': ['Aucune mesure', 'No reading', 'لا قياس'],
  'ring.history': ['Historique', 'History', 'السجل'],
  'ring.alerts': ['Alertes pour cette bague', 'Alerts for this ring', 'تنبيهات هذا الخاتم'],
  'ring.alerts_no_right': ['Alertes non autorisées pour cette bague', 'Alerts not allowed for this ring', 'التنبيهات غير مسموح بها لهذا الخاتم'],
  'ring.duration': ['⏱ %s s', '⏱ %s s', '⏱ %s ث'],
  'ring.error': ['%s · %s', '%s · %s', '%s · %s'],
  'ring.km': ['%s km · %s kcal', '%s km · %s kcal', '%s كم · %s سعرة'],
  'src.manual': ['via G-RHM', 'on G-RHM', 'عبر G-RHM'],
  'src.mqtt': ['via Serveur', 'on Server', 'عبر الخادم'],
  'src.auto': ['auto', 'auto', 'تلقائي'],
  'src.phone': ['via téléphone', 'on phone', 'عبر الهاتف'],
  'src.phone_p': ['prise', 'taken', 'مأخوذ'],
  'src.phone_r': ['actualisée', 'refreshed', 'محدَّث'],
  'src.by': ['par %s', 'by %s', 'بواسطة %s'],
  'cmd.sent': ['Demande envoyée à la Gateway RHM', 'Request sent to the Gateway RHM', 'تم إرسال الطلب إلى بوابة RHM'],
  'cmd.already': ['Mesure déjà en cours : résultat partagé', 'Already measuring: shared result', 'القياس جارٍ: نتيجة مشتركة'],

  // ------------------------------------------------ erreurs de mesure (codes du gateway)
  'err.ring_unbound': ['Bague dissociée', 'Ring unpaired', 'الخاتم غير مرتبط'],
  'err.ring_disconnected': ['Bague hors portée', 'Ring out of range', 'الخاتم خارج النطاق'],
  'err.ring_removed': ['Bague retirée', 'Ring removed', 'الخاتم منزوع'],
  'err.timeout': ['Pas de résultat', 'No result', 'لا توجد نتيجة'],
  'err.measure_failed': ['Mesure échouée', 'Measurement failed', 'فشل القياس'],
  'err.not_supported': ['Non supporté par cette bague', 'Not supported by this ring', 'غير مدعوم'],
  'err.busy': ['Bague occupée', 'Ring busy', 'الخاتم مشغول'],
  'err.cancelled': ['Mesure annulée', 'Measurement cancelled', 'تم إلغاء القياس'],
  'err.no_data': ['Aucune donnée', 'No data', 'لا توجد بيانات'],

  // ------------------------------------------------ vérification « État »
  'st.refresh': ['Actualiser l\'état de la bague', 'Refresh ring status', 'تحديث حالة الخاتم'],
  'st.checking': ['Vérification… %s s / %s s', 'Checking… %s s / %s s', 'جارٍ التحقق… %s ث / %s ث'],
  'st.requested': ['Demande envoyée à la Gateway RHM…', 'Request sent to the Gateway RHM…', 'تم إرسال الطلب…'],
  'st.waiting': ['En attente de la fin de la mesure…', 'Waiting for the measurement to end…', 'في انتظار انتهاء القياس…'],
  'st.worn': ['Bague portée — vérifiée à %s', 'Ring worn — checked at %s', 'الخاتم مرتدى — تم التحقق في %s'],
  'loc.none': ['Bague non entendue', 'Ring not heard', 'الخاتم غير مسموع'],
  'loc.sec': ['il y a %s s', '%s s ago', 'منذ %s ث'],
  'st.reachable': ['Bague à portée — vérifiée à %s', 'Ring in range — checked at %s', 'الخاتم في النطاق — تم التحقق في %s'],
  'st.measured': ['Bague portée — mesure à %s', 'Ring worn — measured at %s', 'الخاتم مرتدى — قياس في %s'],
  'st.measured_removed': ['Bague retirée — mesure %s à %s', 'Ring removed — %s measurement at %s', 'الخاتم منزوع — قياس %s في %s'],
  'st.removed': ['Bague retirée — veuillez porter la bague', 'Ring removed — please wear the ring', 'الخاتم منزوع — يرجى ارتداؤه'],
  'st.unconfirmed': ['Pas de réponse de la bague', 'No answer from the ring', 'لا رد من الخاتم'],
  'pop.back_title': ['Content de vous revoir !', 'Welcome back!', 'مرحبًا بعودتك!'],
  'pop.back_text': ['%s est de nouveau connectée à la GATEWAY RHM.\nVérifier si la bague est portée ?', '%s is connected to the GATEWAY RHM again.\nCheck whether the ring is worn?', '%s متصل ببوابة RHM مجددًا.\nالتحقق مما إذا كان الخاتم مرتدى؟'],
  'pop.back_yes': ['Oui, vérifier', 'Yes, check', 'نعم، تحقق'],
  'pop.back_later': ['Plus tard', 'Later', 'لاحقًا'],
  'pop.busy_title': ['Mesure en cours', 'Measurement in progress', 'القياس جارٍ'],
  'pop.busy_text': ['Veuillez patienter : la vérification de la bague sera lancée à la fin de la mesure en cours (%s).', 'Please wait: the ring check will start when the current measurement ends (%s).', 'يرجى الانتظار: سيبدأ فحص الخاتم عند انتهاء القياس الجاري (%s).'],

  // ------------------------------------------------ historique
  'sl.title': ['Sommeil', 'Sleep', 'النوم'],
  'sl.button': ['Sommeil · 30 dernières nuits', 'Sleep · last 30 nights', 'النوم · آخر 30 ليلة'],
  'sl.none': ['Aucune nuit enregistrée pour l\'instant.\nLa GATEWAY RHM synchronise le sommeil chaque matin.', 'No night recorded yet.\nThe GATEWAY RHM syncs sleep every morning.', 'لا توجد ليالٍ مسجلة بعد.\nتزامن بوابة RHM النوم كل صباح.'],
  'sl.avg': ['Moyenne : %s par nuit · %s nuits', 'Average: %s per night · %s nights', 'المتوسط: %s لكل ليلة · %s ليالٍ'],
  'sl.deep': ['Profond', 'Deep', 'عميق'],
  'sl.light': ['Léger', 'Light', 'خفيف'],
  'sl.rem': ['Paradoxal', 'REM', 'حركة العين'],
  'sl.awake': ['Éveillé', 'Awake', 'مستيقظ'],
  'sl.bed': ['%s → %s', '%s → %s', '%s ← %s'],
  'hist.24h': ['24 h', '24 h', '24 س'],
  'hist.7d': ['7 j', '7 d', '7 أيام'],
  'hist.30d': ['30 j', '30 d', '30 يومًا'],
  'hist.none': ['Aucune mesure sur cette période.', 'No reading in this period.', 'لا توجد قياسات في هذه الفترة.'],
  'hist.stats': ['moy. %s · min %s · max %s', 'avg %s · min %s · max %s', 'المتوسط %s · الأدنى %s · الأعلى %s'],
  'hist.no_right': ['Historique non autorisé', 'History not allowed', 'السجل غير مسموح'],

  // ------------------------------------------------ alertes
  'al.none': ['Aucune alerte pour l\'instant.', 'No alert yet.', 'لا توجد تنبيهات بعد.'],

  // ------------------------------------------------ profil
  'pr.rings': ['%s bague(s) suivie(s)', '%s ring(s) followed', '%s خاتم'],
  'pr.lang': ['Langue', 'Language', 'اللغة'],
  'pr.alerts': ['Recevoir les alertes', 'Receive alerts', 'استلام التنبيهات'],
  'pr.alerts_sub': ['Retirée · hors portée · dissociée · Gateway RHM hors ligne · batterie faible', 'Removed · out of range · unpaired · Gateway RHM offline · low battery', 'منزوع · خارج النطاق · غير مرتبط · بوابة RHM غير متصلة · بطارية منخفضة'],
  'pr.notif_on': ['Notifications du téléphone actives', 'Phone notifications active', 'إشعارات الهاتف مفعلة'],
  'pr.notif_off': ['Notifications du téléphone non configurées (alertes visibles dans l\'app)', 'Phone notifications not configured (alerts shown in the app)', 'إشعارات الهاتف غير مهيأة (التنبيهات داخل التطبيق)'],
  'pr.password': ['Changer mon mot de passe', 'Change my password', 'تغيير كلمة المرور'],
  'pr.old': ['Mot de passe actuel', 'Current password', 'كلمة المرور الحالية'],
  'pr.new': ['Nouveau mot de passe (6 caractères min.)', 'New password (6 characters min.)', 'كلمة مرور جديدة (6 أحرف على الأقل)'],
  'pr.pass_ok': ['Mot de passe changé', 'Password changed', 'تم تغيير كلمة المرور'],
  'pr.logout': ['Se déconnecter', 'Sign out', 'تسجيل الخروج'],
  'pr.server': ['Serveur : %s', 'Server: %s', 'الخادم: %s'],

  // ------------------------------------------------ temps
  't.now': ['à l\'instant', 'just now', 'الآن'],
  't.min': ['il y a %s min', '%s min ago', 'منذ %s د'],
  't.h': ['il y a %s h', '%s h ago', 'منذ %s س'],
  't.yesterday': ['hier', 'yesterday', 'أمس'],
};
