package com.eis.qringmqtt

import android.app.Application
import com.eis.qringmqtt.ble.RingManager
import com.eis.qringmqtt.data.AppState

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        AppState.init(this)
        RingManager.init(this)
    }
}
