package com.qcwireless.sdksample

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import com.google.gson.Gson
import com.hjq.permissions.OnPermissionCallback
import com.hjq.permissions.XXPermissions
import com.oudmon.ble.base.bean.SleepDisplay
import com.oudmon.ble.base.bluetooth.BleAction
import com.oudmon.ble.base.bluetooth.BleOperateManager
import com.oudmon.ble.base.bluetooth.DeviceManager
import com.oudmon.ble.base.bluetooth.ListenerKey
import com.oudmon.ble.base.communication.CommandHandle
import com.oudmon.ble.base.communication.ICommandResponse
import com.oudmon.ble.base.communication.ILargeDataLaunchSleepResponse
import com.oudmon.ble.base.communication.ILargeDataSleepResponse
import com.oudmon.ble.base.communication.LargeDataHandler
import com.oudmon.ble.base.communication.bigData.AlarmNewEntity
import com.oudmon.ble.base.communication.bigData.IIntervalTemperatureCallback
import com.oudmon.ble.base.communication.bigData.IntervalBloodOxygenEntity
import com.oudmon.ble.base.communication.bigData.bean.IntervalTemperatureEntity
import com.oudmon.ble.base.communication.req.BloodOxygenSettingReq
import com.oudmon.ble.base.communication.req.BluetoothCloseReq
import com.oudmon.ble.base.communication.req.PhoneIdReq
import com.oudmon.ble.base.communication.req.StartHeartRateReq
import com.oudmon.ble.base.communication.req.TouchControlReq
import com.oudmon.ble.base.communication.responseImpl.DeviceNotifyListener
import com.oudmon.ble.base.communication.rsp.BaseRspCmd
import com.oudmon.ble.base.communication.rsp.BloodOxygenSettingRsp
import com.oudmon.ble.base.communication.rsp.BluetoothCloseRsp
import com.oudmon.ble.base.communication.rsp.DeviceNotifyRsp
import com.oudmon.ble.base.communication.rsp.PhoneIdRsp
import com.oudmon.ble.base.communication.rsp.SleepNewProtoResp
import com.oudmon.ble.base.communication.rsp.StopHeartRateRsp
import com.oudmon.ble.base.communication.utils.BLEDataFormatUtils
import com.oudmon.ble.base.util.DateUtil
import com.qcwireless.sdksample.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private val test = Test()
    private lateinit var myDeviceNotifyListener: MyDeviceNotifyListener

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        initView()
    }

    private fun initView() {
        setOnClickListener(binding.tvScan) {
            requestLocationPermission(this@MainActivity, PermissionCallback())
        }

        myDeviceNotifyListener = MyDeviceNotifyListener()

        binding.run {
            tvName.text = DeviceManager.getInstance().deviceName
            val connect = BleOperateManager.getInstance().isConnected
            tvConnect.text = connect.toString()

            setOnClickListener(
                btnSetTime,
                btnFindWatch,
                btnBattery,
                btnTimeUnit,
                btnMsgTest,
                btnAlarmRead,
                btnAlarmWrite,
                btnSyncBloodoxygen,
                btnTakePicture,
                btnMusic,
                btnCall,
                btnTarget,
                tvReconnect,
                tvDisconnect,
                btnWatchFace,
                btnSleep,
                btnSleepCalc,
                heart1,
                heart2,
                heart3,
                push1,
                push2,
                temperature1,
                temperature2,
                userprofile1,
                userprofile2,
                addListener1,
                addListener2,
                addListener3,
                ota,
                bt,
                btnPpg,
                btnSport,
                pressure1,
                pressure2,
                btnOneKey,
                tvTouch,
                btnIntervalOxygen,
                btnIntervalOxygenAdd,
                btnUserId,
                btnUserIdWrite,
                btnTemperatureRead,
                btnTemperatureMeasureControl,
                btnCloseBlueTooth,
                btnNewSleep,
                btnShutdown,
                btnHeartRateRead,
                btnHeartRateWrite,
                btnPalmScreenRead,
                btnPalmScreenWrite,
            ) {
                when (this) {
                    tvReconnect -> {
                        BleOperateManager.getInstance()
                            .connectDirectly(DeviceManager.getInstance().deviceAddress)
                    }

                    tvDisconnect -> {
                        BleOperateManager.getInstance().unBindDevice()
                    }

                    btnSetTime -> {
                        test.setTime()
                    }

                    btnFindWatch -> {
//                        test.findPhone()
//                        BleOperateManager.getInstance().manualModeHrv{resultEntity -> Log.i("11111", "---------pressure" + resultEntity.value + "---"+resultEntity.rri)}
                    }

                    btnBattery -> {
                        test.battery
                    }

                    btnTimeUnit -> {
                        test.readMetricAndTimeFormat()
                    }

                    btnMsgTest -> {
                        test.pushMsg()
                    }

                    btnAlarmRead -> {
                        test.readAlarm()
                    }

                    btnAlarmWrite -> {
                        val list = mutableListOf<AlarmNewEntity.AlarmBean>()
                        val bean = AlarmNewEntity.AlarmBean()
                        bean.content = "1234"
                        bean.min = DateUtil().todayMin + 1
                        bean.repeatAndEnable = 0xff
                        bean.alarmLength = 4 + bean.content.encodeToByteArray().size
                        list.add(bean)
                        val entity = AlarmNewEntity()
                        entity.total = 1
                        entity.data = list
                        test.writeAlar(entity)
                    }

                    btnSyncBloodoxygen -> {
                        test.bloodOxygen()
                    }

                    btnTakePicture -> {
                        test.takePicture()
                    }

                    btnMusic -> {
                        test.music()
                    }

                    btnCall -> {
                        test.call()
                    }

                    btnTarget -> {
                        test.setTarget()
                    }

                    btnWatchFace -> {
                        test.watchFace()
                    }

                    btnSleep -> {
                        test.sleep()
                    }

                    btnSleepCalc -> {
//                        test.newSleep()
                        test.contactList()
                    }

                    heart1 -> {
//                        test.heart()
                        test.heartSync()
//                        LargeDataHandler.getInstance().syncManualHeartRateList(
//                            0
//                        ) {
//                            Log.i("",it.index.toString())
//                            Log.i("",it.data.size.toString())
//                        }

                    }

                    heart2 -> {
                        test.bp()
                    }

                    heart3 -> {
                        test.spo2()
                    }

                    pressure1 -> {
                        test.pressure()
                    }

                    pressure2 -> {
                        test.hrv()
                    }

                    push1 -> {
                        test.push1()
                    }

                    push2 -> {
                        test.push2()
                    }

                    temperature1 -> {
                        test.registerTempCallback()
                        test.syncAutoTemperature()
                    }

                    temperature2 -> {
                        test.syncManual()
                    }

                    userprofile1 -> {
                        test.setUserProfile()
                    }

                    userprofile2 -> {
                        test.getUserProfile()
                    }

                    addListener1 -> {
                        BleOperateManager.getInstance()
                            .addOutDeviceListener(ListenerKey.Heart, myDeviceNotifyListener)
                    }

                    addListener2 -> {
                        BleOperateManager.getInstance().removeNotifyListener(ListenerKey.Heart)
                    }

                    addListener3 -> {
                        BleOperateManager.getInstance().removeNotifyListener(ListenerKey.All)
                    }

                    ota -> {
                        startKtxActivity<OtaActivity>()
//                        BleOperateManager.getInstance().ringCalibration(false
//                        ) {
//                            Log.i("11119998",it.success.toString())
//                        }
                    }

                    bt -> {
                        BleOperateManager.getInstance().ringCalibration(
                            true
                        ) {
                            Log.i("11119999", it.success.toString())
                        }
//                        //获取BT的地址和名称
//                        LargeDataHandler.getInstance().syncClassicBluetooth {
//                            //返回BT的地址和名称
//                        }
//                        //查询系统蓝牙是否已经绑定这个地址
//                        val device = BleOperateManager.getInstance()
//                            .getMacSystemBond(String mac)
//                        //如果device ！=null代表已经绑定，调用连接
//                        //rtk
//                        BleOperateManager.getInstance().connectRtkSPP(device)
//                        //bk
//                        BleOperateManager.getInstance().createBondBlueTooth(device)
//                        //如果没有绑定，device==null,启动经典蓝牙扫描，可自己实现
//                        BleOperateManager.getInstance().classicBluetoothStartScan()
//                        //监听系统经典蓝牙扫描广播监听，  BluetoothDevice.ACTION_FOUND
//                        //通过返回的设备mac和手表给的匹配，
//                        BleOperateManager.getInstance().connectRtkSPP(device)
                    }

                    btnPpg -> {
                        Log.i("HeartTTest", "TYPE_Heart_Raw_Data_Measurement greenLightPpg1:")
                        CommandHandle.getInstance()
                            .executeReqCmd(
                                StartHeartRateReq.getSimpleReq(StartHeartRateReq.TYPE_Heart_Raw_Data_Measurement),
                                object : ICommandResponse<StopHeartRateRsp> {
                                    override fun onDataResponse(resultEntity: StopHeartRateRsp) {
                                        if (resultEntity.errCode == 0x00.toByte() && resultEntity.type == StartHeartRateReq.TYPE_Heart_Raw_Data_Measurement) {
                                            if (resultEntity.value > 0) {
                                                Log.i("111", resultEntity.rri.toString())
                                                binding.tvHeart.setTextColor(Color.RED)
                                                binding.tvHeart.text = resultEntity.rri.toString()
                                            }
                                            Log.i("HeartTTest", "greenLightPpg1:"+resultEntity.greenLightPpg.toString())
                                        }
                                    }
                                })

//                        for(index in 0..6){
//                            val entity = AlarmEntity(index, 1, index+5, index*5, 0x80.toByte())
//                            CommandHandle.getInstance().executeReqCmdNoCallback(
//                                SetDrinkAlarmReq(entity)
//                            )
//                        }
                    }

                    btnSport -> {
//                        test.syncSport()
//                        test.heartEnable()
                        binding.tvHard.text = MyApplication.getInstance.hardwareVersion
                        binding.tvFir.text = MyApplication.getInstance.firmwareVersion
                    }

                    btnOneKey -> {
//                        BleOperateManager.getInstance().oneClickMeasurement(ICommandResponse<StopHeartRateRsp> {
//                            Log.i("sdk_demo",Gson().toJson(it))
//                        }, false)

                        BleOperateManager.getInstance()
                            .manualModeHeartRateRawData(ICommandResponse<StopHeartRateRsp> {
                                Log.i("sdk_demo", Gson().toJson(it))
                            }, 25, false)
                        BleAction.BLE_DESCRIPTOR_WRITE
                    }

                    tvTouch -> {
                        BleOperateManager.getInstance()
                            .addOutDeviceListener(0x2d, myDeviceNotifyListener)
                        CommandHandle.getInstance()
                            .executeReqCmd(TouchControlReq.getWriteInstance(9, true, 5), null)
//                        //Set RT11 Touch muslim Function
//                        CommandHandle.getInstance().executeReqCmd(TouchControlReq.getWriteTpSleepInstance(3,1),
//                            null)
                    }

                    btnIntervalOxygen -> {
                        CommandHandle.getInstance()
                            .executeReqCmd(
                                BloodOxygenSettingReq.getReadInstance(),
                                object : ICommandResponse<BloodOxygenSettingRsp> {
                                    override fun onDataResponse(bloodOxygenSettingRsp: BloodOxygenSettingRsp) {
                                        Log.i(
                                            "sdk_demo",
                                            "bloodOxygenSettingRsp->getReadInstance:" + Gson().toJson(
                                                bloodOxygenSettingRsp
                                            )
                                        )
                                    }
                                })
                        LargeDataHandler.getInstance().syncIntervalBloodOxygenWithCallback(
                            0,
                            fun(p0: IntervalBloodOxygenEntity) {
                                Log.i(
                                    "sdk_demo",
                                    "syncIntervalBloodOxygenWithCallback->" + Gson().toJson(p0)
                                )
                                Log.i(
                                    "sdk_demo",
                                    "syncIntervalBloodOxygenWithCallback->size:" + p0.array.size
                                )
                            })
                    }

                    btnIntervalOxygenAdd -> {
                        CommandHandle.getInstance()
                            .executeReqCmd(
                                BloodOxygenSettingReq.getWriteInstance(true, intervalMin.toByte()),
                                object : ICommandResponse<BloodOxygenSettingRsp> {
                                    override fun onDataResponse(bloodOxygenSettingRsp: BloodOxygenSettingRsp) {
                                        intervalMin++
                                        Log.i(
                                            "sdk_demo",
                                            "bloodOxygenSettingRsp->getWriteInstance:"
                                        )
                                    }
                                })
                    }

                    btnUserId -> {
                        CommandHandle.getInstance()
                            .executeReqCmd(
                                PhoneIdReq.getReadInstance(),
                                object : ICommandResponse<PhoneIdRsp> {
                                    override fun onDataResponse(phoneIdRsp: PhoneIdRsp) {
                                        Log.i(
                                            "sdk_demo",
                                            "phoneIdRsp->getReadInstance->userId:" + phoneIdRsp.getUserId()
                                        )
                                    }
                                })

                    }

                    btnUserIdWrite -> {
                        CommandHandle.getInstance()
                            .executeReqCmd(
                                PhoneIdReq.getWriteInstance("123456789123"),
                                object : ICommandResponse<PhoneIdRsp> {
                                    override fun onDataResponse(phoneIdRsp: PhoneIdRsp) {
                                        Log.i(
                                            "sdk_demo",
                                            "phoneIdRsp->getWriteInstance:"
                                        )
                                    }
                                })
                    }

                    btnTemperatureRead -> {
//                        //support interval temperature
//                        CommandHandle.getInstance()
//                            .executeReqCmd(
//                                DeviceSupportReq.getReadInstance(),
//                                object : ICommandResponse<DeviceSupportFunctionRsp> {
//                                    override fun onDataResponse(deviceSupportFunctionRsp: DeviceSupportFunctionRsp) {
//                                        Log.i(
//                                            "sdk_demo",
//                                            "deviceSupportFunctionRsp->getReadInstance->supportIntervalTemperature:" + deviceSupportFunctionRsp.supportIntervalTemperature
//                                        )
//                                    }
//                                })
//                        //read temperature setting.type:temperature 3
//                        CommandHandle.getInstance()
//                            .executeReqCmd(
//                                SugarLipidsSettingReq.getReadInstance(3),
//                                object : ICommandResponse<BloodSugarLipidsSettingRsp> {
//                                    override fun onDataResponse(bloodSugarLipidsSettingRsp: BloodSugarLipidsSettingRsp) {
//                                        Log.i(
//                                            "sdk_demo",
//                                            "deviceSupportFunctionRsp->getReadInstance->bloodSugarLipidsSettingRsp:" + bloodSugarLipidsSettingRsp
//                                        )
//                                    }
//                                })

//                        //temperature data.dayIndex:today 0,yesterday 1
//                        LargeDataHandler.getInstance().syncIntervalTemperatureWithCallback(
//                            1,
//                            object : IIntervalTemperatureCallback {
//                                override fun readIntervalTemperature(p0: IntervalTemperatureEntity) {
//                                    Log.i(
//                                        "sdk_demo",
//                                        "syncIntervalTemperatureWithCallback->" + Gson().toJson(p0)
//                                    )
//                                    Log.i(
//                                        "sdk_demo",
//                                        "syncIntervalTemperatureWithCallback->size:" + p0.array.size
//                                    )
//                                }
//                            }
//                        )
//                        //temperature data.dayIndex:today 0,yesterday 1
                        LargeDataHandler.getInstance().syncIntervalThreeTemperatureWithCallback(
                            0,
                            object : IIntervalTemperatureCallback {
                                override fun readIntervalTemperature(p0: IntervalTemperatureEntity) {
                                    Log.i(
                                        "sdk_demo",
                                        "syncIntervalThreeTemperatureWithCallback->" + Gson().toJson(
                                            p0
                                        )
                                    )
                                    for (i in 0 until p0.values.size) {
                                        val it = p0.values[i]
                                        Log.i(
                                            "sdk_demo",
                                            "manualThreeTemperature->value1:" + it.value1 + ",value2:" + it.value2 + ",value3:" + it.value3
                                        )
                                    }
                                    Log.i(
                                        "sdk_demo",
                                        "syncIntervalThreeTemperatureWithCallback->size:" + p0.values.size
                                    )
                                }
                            }
                        )
                    }

                    btnTemperatureMeasureControl -> {
                        //Setting temperature 1min interval.type:temperature 3,value is your interval
//                        CommandHandle.getInstance()
//                            .executeReqCmd(
//                                SugarLipidsSettingReq.getWriteInstance(3, true, 2),
//                                object : ICommandResponse<BloodSugarLipidsSettingRsp> {
//                                    override fun onDataResponse(bloodSugarLipidsSettingRsp: BloodSugarLipidsSettingRsp) {
//                                        Log.i(
//                                            "sdk_demo",
//                                            "deviceSupportFunctionRsp->getWriteInstance->:"
//                                        )
//                                    }
//                                })
                        BleOperateManager.getInstance().manualThreeTemperature({ p0 ->
                            p0.intervalTemperature?.let {
                                Log.i(
                                    "sdk_demo",
                                    "manualThreeTemperature->value1:" + it.value1 + ",value2:" + it.value2 + ",value3:" + it.value3
                                )
                            }
                        }, false)
                    }

                    btnCloseBlueTooth -> {
                        CommandHandle.getInstance()
                            .executeReqCmd(
                                BluetoothCloseReq.getWriteInstance(),
                                object : ICommandResponse<BluetoothCloseRsp> {
                                    override fun onDataResponse(bluetoothCloseRsp: BluetoothCloseRsp) {
                                        Log.i(
                                            "sdk_demo",
                                            "bluetoothCloseRsp->getWriteInstance->:"
                                        )
                                    }
                                })
                    }

                    btnNewSleep -> {
                        LargeDataHandler.getInstance().syncSleepList(0, object :
                            ILargeDataSleepResponse {
                            override fun sleepData(p0: SleepDisplay?) {
                                Log.i(
                                    "sdk_demo",
                                    "syncSleepDataCallback->" + Gson().toJson(p0)
                                )
                            }
                        }, object :
                            ILargeDataLaunchSleepResponse {
                            override fun sleepData(p0: SleepNewProtoResp?) {
                                Log.i(
                                    "sdk_demo",
                                    "syncLaunchSleepDataCallback->" + Gson().toJson(p0)
                                )
                            }
                        })
                    }

                    btnShutdown -> {
                        BleOperateManager.getInstance().shutdown()
                    }

                    btnHeartRateRead -> {
                        //too Low/High Reminder is notify in DeviceNotifyListener 0x3A
                        test.heartRead()
                        //add  Heart rate tooLow/High Reminder Listener
                        BleOperateManager.getInstance()
                            .addOutDeviceListener(ListenerKey.Heart, myDeviceNotifyListener)
                    }

                    btnHeartRateWrite -> {
                        test.heartWrite()
                    }
                    btnPalmScreenRead-> {
                        test.palmScreenRead()
                    }

                    btnPalmScreenWrite -> {
                        test.palmScreenWrite()
                    }
                }
            }

        }
    }

    private var intervalMin = 1


    inner class MyDeviceNotifyListener : DeviceNotifyListener() {
        override fun onDataResponse(resultEntity: DeviceNotifyRsp?) {
            if (resultEntity!!.status == BaseRspCmd.RESULT_OK) {
                BleOperateManager.getInstance().removeOthersListener()
                when (resultEntity.dataType) {
                    1 -> {
                        //手表心率测试
                    }

                    2 -> {
                        //手表血压测试
                    }

                    3 -> {
                        //手表血氧测试
                    }

                    4 -> {
                        //手表计步详情变化
                    }

                    5 -> {
                        //当天手表体温变化
                    }

                    7 -> {
                        //生成新的运动记录
                    }

                    0x2d -> {
                        //The custom function button is triggered
                        val event = BLEDataFormatUtils.bytes2Int(
                            byteArrayOf(
                                resultEntity.loadData[1]
                            )
                        )
//                        event:0 null  1:decline  2：Slide up  3：Single  4：Long press
                        Log.i("touch event", event.toString())
                    }

                    0x3A -> {//must add  Heart rate tooLow/High Reminder Listener:ListenerKey.Heart

                        //BleOperateManager.getInstance()
                        //.addOutDeviceListener(ListenerKey.Heart, myDeviceNotifyListener)

                        //Heart Rate too low/high Reminder
                        val type = BLEDataFormatUtils.bytes2Int(
                            byteArrayOf(
                                resultEntity.loadData[1]
                            )
                        )
                        if (type == 1) {//too low

                        } else if (type == 2) {//too high

                        }
                        //Heart Rate value
                        val value = BLEDataFormatUtils.bytes2Int(
                            byteArrayOf(
                                resultEntity.loadData[2]
                            )
                        )
                        Log.i("HeartRateTest", "HeartRateReminder type:$type value:$value")
                    }

                    0x3b -> {
                        //The measure temperature
                        val value = BLEDataFormatUtils.bytes2Int(
                            byteArrayOf(
                                resultEntity.loadData[1],
                                resultEntity.loadData[2]
                            )
                        )
                        if (value > 0) {
                            Log.i(
                                "touch event",
                                "temperature event->temperature value:" + (value / 100.0).toString()
                            )
                        }
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        try {
            if (!BluetoothUtils.isEnabledBluetooth(this)) {
                val intent = Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    if (ActivityCompat.checkSelfPermission(
                            this,
                            Manifest.permission.BLUETOOTH_CONNECT
                        ) != PackageManager.PERMISSION_GRANTED
                    ) {
                        return
                    }
                }
                startActivityForResult(intent, 300)
            }
        } catch (e: Exception) {
        }
        if (!hasBluetooth(this)) {
            requestBluetoothPermission(this, BluetoothPermissionCallback())
        }

        binding.tvName.text = DeviceManager.getInstance().deviceName
        requestAllPermission(this, OnPermissionCallback { permissions, all -> })
    }

    inner class PermissionCallback : OnPermissionCallback {
        override fun onGranted(permissions: MutableList<String>, all: Boolean) {
            if (!all) {

            } else {
                startKtxActivity<DeviceBindActivity>()
            }
        }

        override fun onDenied(permissions: MutableList<String>, never: Boolean) {
            super.onDenied(permissions, never)
            if (never) {
                XXPermissions.startPermissionActivity(this@MainActivity, permissions);
            }
        }

    }

    inner class BluetoothPermissionCallback : OnPermissionCallback {
        override fun onGranted(permissions: MutableList<String>, all: Boolean) {
            if (!all) {

            }
        }

        override fun onDenied(permissions: MutableList<String>, never: Boolean) {
            super.onDenied(permissions, never)
            if (never) {
                XXPermissions.startPermissionActivity(this@MainActivity, permissions)
            }
        }

    }

    inner class AllPermissionCallback : OnPermissionCallback {
        override fun onGranted(permissions: MutableList<String>, all: Boolean) {

        }

        override fun onDenied(permissions: MutableList<String>, never: Boolean) {
            super.onDenied(permissions, never)

        }
    }

}
