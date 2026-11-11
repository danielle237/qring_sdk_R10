package com.eis.qringmqtt

import android.app.Application
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState
import com.eis.qringmqtt.data.I18n
import com.eis.qringmqtt.ui.MainActivity
import com.eis.qringmqtt.ui.StatusCheck

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        AppState.init(this)
        RingManager.init(this)
        I18n.isTv = MainActivity.detectTv(this)
        // État de la bague + popups (hors portée, retirée, reconnectée)
        StatusCheck.init()
    }
}
