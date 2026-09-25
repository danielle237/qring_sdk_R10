package com.qcwireless.sdksample

import android.content.Context
import android.util.Log
import com.androidnetworking.AndroidNetworking
import com.androidnetworking.common.Priority
import com.androidnetworking.error.ANError
import com.androidnetworking.interfaces.DownloadListener
import com.google.gson.Gson
import com.oudmon.ble.base.bean.SleepDetail
import com.oudmon.ble.base.bean.SleepDisplay
import com.oudmon.ble.base.bluetooth.BleOperateManager
import com.oudmon.ble.base.bluetooth.ListenerKey
import com.oudmon.ble.base.communication.CommandHandle
import com.oudmon.ble.base.communication.Constants
import com.oudmon.ble.base.communication.ICommandResponse
import com.oudmon.ble.base.communication.ILargeDataLaunchSleepResponse
import com.oudmon.ble.base.communication.ILargeDataSleepResponse
import com.oudmon.ble.base.communication.LargeDataHandler
import com.oudmon.ble.base.communication.bigData.AlarmNewEntity
import com.oudmon.ble.base.communication.bigData.BloodOxygenEntity
import com.oudmon.ble.base.communication.bigData.IBloodOxygenCallback
import com.oudmon.ble.base.communication.bigData.bean.ContactBean
import com.oudmon.ble.base.communication.dfu_temperature.TemperatureEntity
import com.oudmon.ble.base.communication.dfu_temperature.TemperatureOnceEntity
import com.oudmon.ble.base.communication.entity.AlarmEntity
import com.oudmon.ble.base.communication.entity.StartEndTimeEntity
import com.oudmon.ble.base.communication.file.FileHandle
import com.oudmon.ble.base.communication.file.SimpleCallback
import com.oudmon.ble.base.communication.req.*
import com.oudmon.ble.base.communication.rsp.*
import com.oudmon.ble.base.communication.sport.SportPlusHandle
import com.oudmon.ble.base.util.MessPushUtil
import com.oudmon.ble.base.util.SleepAnalyzerUtils
import okhttp3.*
import org.greenrobot.eventbus.EventBus
import org.json.JSONObject
import java.io.File
import java.util.TimeZone


class Test {
    var commandHandle = CommandHandle.getInstance()
    var mContext: Context? = null
    fun setTime() {
        commandHandle.executeReqCmd(SetTimeReq(0)) { }
    }

    fun findPhone() {
        commandHandle.executeReqCmd(FindDeviceReq()) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
            }
        }
    }

    val battery: Unit
        get() {
            commandHandle.executeReqCmd(SimpleKeyReq(Constants.CMD_GET_DEVICE_ELECTRICITY_VALUE)) { resultEntity ->
                if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                }
            }
        }

    fun pushMsg() {
//        val bean= SetANCSReq()
//        bean.setFacebook(true)
//        CommandHandle.getInstance().executeReqCmd(
//            bean, null
//        )
        MessPushUtil.pushMsg(5, "hello world")
    }

    fun readAlarm() {
        LargeDataHandler.getInstance()
            .readAlarmWithCallback { entity -> Log.i(TAG, entity.toString()) }
    }

    fun bloodOxygen() {
        LargeDataHandler.getInstance().syncBloodOxygenWithCallback(object : IBloodOxygenCallback {
            override fun readBloodOxygen(p0: List<BloodOxygenEntity>?) {
                if (p0 != null) {
                    Log.i(
                        "sdk_demo",
                        "syncBloodOxygenWithCallback->getReadInstance:" + Gson().toJson(p0)
                    )
                } else {
                    Log.i(
                        "sdk_demo",
                        "syncBloodOxygenWithCallback->getReadInstance:" + "not data"
                    )
                }
            }
        })
    }

    fun writeAlar(entity: AlarmNewEntity?) {
        LargeDataHandler.getInstance().writeAlarm(entity)
    }

    fun readMetricAndTimeFormat() {
        commandHandle.executeReqCmd(TimeFormatReq.getReadInstance()) { }
    }

    fun setUserProfile() {
        //    private boolean m24Format = true;
        //    private int mMetric = 0;
        //    private int mSex = 0;
        //    private int mAge = 30;
        //    private int mHeight = 170;
        //    private int mWeight = 65;
        //    private int mSbp = 115;
        //    private int mDbp = 75;
        //    private int mRate = 160;
        commandHandle.executeReqCmd(
            TimeFormatReq.getWriteInstance(
                true,
                0,
                0,
                30,
                170,
                65,
                115,
                75,
                160
            )
        ) { }
    }

    fun getUserProfile() {
        commandHandle.executeReqCmd(TimeFormatReq.getReadInstance()) { resp ->
            Log.i(TAG, resp.toString() + "")
        }
    }

    fun takePicture() {
        CommandHandle.getInstance().executeReqCmd(CameraReq(CameraReq.ACTION_INTO_CAMARA_UI), null)
        BleOperateManager.getInstance()
            .addNotifyListener(Constants.CMD_TAKING_PICTURE.toInt()) { resultEntity ->

            }
    }

    fun music() {
        BleOperateManager.getInstance()
            .addNotifyListener(Constants.CMD_MUSIC_COMMAND.toInt()) { resultEntity ->

            }
    }

    fun call() {
        BleOperateManager.getInstance()
            .addNotifyListener(Constants.CMD_PHONE_NOTIFY.toInt()) { resultEntity ->

            }
    }

    fun setTarget() {
        CommandHandle.getInstance().executeReqCmdNoCallback(
            TargetSettingReq.getWriteInstance(
                8000, 500, 3000, 60, 600
            )
        )

        CommandHandle.getInstance().executeReqCmd(
            TargetSettingReq.getWriteInstance(
                8000, 500, 3000, 60, 600
            )
        ) { resultEntity ->
            Log.i("11111", "11111")
        }
    }

    fun watchFace() {
        /***
         * 1.Get the watch face from the orange server
         * 2.Download watch face files and preview images
         * 3.Transfer the local file path to the method, the watch face will be updated
         */
        val client: OkHttpClient = OkHttpClient.Builder().build()
        val qcUrl =
            "https://api1.qcwxkjvip.com/qcwx/external/device/dials?hardwareVersion=" + MyApplication.getInstance.hardwareVersion + "&version=0&customerId=102"
        val request =
            Request.Builder().url(qcUrl).header("token", "e084e6c97ad831ed7716b17504cd0c06").get()
                .build()
        val call = client.newCall(request)
//        call.enqueue(object : Callback() {
//            override fun onFailure(call: Call, e: IOException) {
//
//            }
//
//            override fun onResponse(call: Call, response: Response) {
//                val result = response.body!!.string()
//                Log.i("",result)
//                val obj=JSONObject(result)
//                val dataObj=obj.getJSONObject("data")
//                val array=dataObj.getJSONArray("list")
//                if(array.length()>0){
//                    val b = array.get(0) as JSONObject
//                    val url=b.getString("binUrl")
//                    val name=b.getString("name")
//                    downloadWatchFaceFile(url,name)
//                }
//
//            }
//        })
    }

    fun downloadWatchFaceFile(url: String, name: String) {
        val parentFile =
            File(MyApplication.getInstance.getAppRootFile(MyApplication.CONTEXT), "face")
        AndroidNetworking.download(url, parentFile.toString(), name)
            .setTag(name)
            .setPriority(Priority.MEDIUM)
            .build()
            .setDownloadProgressListener { bytesDownloaded, totalBytes ->
                Log.i(TAG, (bytesDownloaded * 100 / totalBytes).toString())
            }
            .startDownload(object : DownloadListener {
                override fun onDownloadComplete() {
                    FileHandle.getInstance().currFileType = FileHandle.TypeMarketWatchFace
                    FileHandle.getInstance().registerCallback(object : SimpleCallback() {
                        override fun onProgress(percent: Int) {
                            super.onProgress(percent)
                            Log.i(TAG, percent.toString() + "")
                        }

                        override fun onComplete() {
                            super.onComplete()
                        }
                    })
                    FileHandle.getInstance().initRegister()
                    val prepare = FileHandle.getInstance()
                        .executeFilePrepare(File(parentFile.toString(), name).absolutePath)
                    if (prepare) {
                        FileHandle.getInstance().executeFileInit(name, 0x36)
                    } else {
                        Log.i(TAG, prepare.toString() + "")
                    }
                }

                override fun onError(anError: ANError?) {
                }
            })
    }

    fun sleep() {
//        final SleepDetail[] b = new SleepDetail[1];
//        final SleepDetail[] yes = new SleepDetail[1];
//        SleepAnalyzerUtils.getInstance().syncSleepDetail("E7:E9:42:AE:59:1B", 1, new ISleepCallback() {
//            @Override
//            public void sleepData(SleepDetail detail) {
//                yes[0] =detail;
//                Log.i(TAG, yes[0].toString());
//            }
//        });
//        SleepAnalyzerUtils.getInstance().syncSleepDetail("E7:E9:42:AE:59:1B", 2, new ISleepCallback() {
//            @Override
//            public void sleepData(SleepDetail detail) {
//                b[0] =detail;
//                Log.i(TAG, b[0].toString());
//            }
//        });
//        SleepAnalyzerUtils.getInstance()
//            .syncSleepReturnSleepDisplay("E7:E9:42:AE:59:1B", 5) { display ->
//                if (display != null) {
//                    Log.i(TAG, display.toString())
//                }
//            }
        newSleep()
    }

    fun newSleep() {
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

    fun contactList() {
        val list = mutableListOf<ContactBean>()
        for (item in 1..50) {
            val bean = ContactBean()
            bean.contactName = "11111$item"
            bean.phoneNumber = "18682313467"
            list.add(bean)
        }
        LargeDataHandler.getInstance().syncContactMore(list) {
            Log.i(TAG, it.type.toString())
        }
    }

    fun heartSync() {
        val time = (getTimeZone() * 3600).toInt()
        val nowTime = System.currentTimeMillis() / 1000L + time
        CommandHandle.getInstance().executeReqCmd(
            ReadHeartRateReq(nowTime),
            ICommandResponse<ReadHeartRateRsp> {
                Log.i("log", it.getmHeartRateArray().size.toString() + "")
            })
    }

    private fun getTimeZone(): Float {
        return TimeZone.getDefault().getOffset(System.currentTimeMillis()) / (3600 * 1000f)
    }

    fun heart() {
        BleOperateManager.getInstance().manualModeHeart({ resultEntity ->
            Log.i(
                TAG,
                resultEntity.errCode.toString() + "---------" + resultEntity.value + "---" + resultEntity.rri
            )
        }, false)
    }

    fun bp() {
        BleOperateManager.getInstance()
            .manualModeBP(
                { resultEntity -> Log.i(TAG, "---------" + resultEntity.value + "") },
                false
            )
    }


    fun hrv() {
        BleOperateManager.getInstance()
            .manualModeHrv(
                { resultEntity -> Log.i(TAG, "---------" + resultEntity.value + "") },
                false
            )
    }


    fun spo2() {
        BleOperateManager.getInstance()
            .manualModeSpO2({ resultEntity ->
                Log.i(
                    TAG,
                    "---------spo2" + resultEntity.value + ""
                )
            }, false)
    }

    fun pressure() {
        BleOperateManager.getInstance()
            .manualModePressure({ resultEntity ->
                Log.i(
                    TAG,
                    "---------pressure" + resultEntity.value + ""
                )
            }, false)
    }

    fun syncPressure() {
        CommandHandle.getInstance()
            .executeReqCmd(
                PressureReq(0),
                ICommandResponse<PressureRsp> {

                })
    }

    fun pressureEnable() {
        CommandHandle.getInstance().executeReqCmd(
            PressureSettingReq.getWriteInstance(true),
            ICommandResponse<PressureSettingRsp> {

            })
    }

    fun syncSport() {
        val syncSport = SportPlusHandle()
        syncSport.timeFormat = "yyyy-MM-dd HH:mm"
        syncSport.syncSportPlus { errorCode, t ->

        }
        //0 is passed for the first synchronization, and the time of the last movement after synchronization is passed later.
        syncSport.cmdSummary(0)
    }

    fun push1() {
        commandHandle.executeReqCmd(
            SimpleKeyReq(Constants.CMD_GET_ANCS_ON_OFF), object : ICommandResponse<ReadANCSRsp> {
                override fun onDataResponse(resultEntity: ReadANCSRsp) {
                    Log.i(TAG, "---------" + resultEntity.isWechat)
                    Log.i(TAG, "---------" + resultEntity.isCall)
                }
            }
        )
    }

    fun push2() {
        /***
         *
         * bit0：1：来电提醒使能，0：来电提醒关闭
        Bit1：1：短信提醒使能，0：短信提醒关闭
        Bit2：1：QQ提醒使能， 0：QQ提醒关闭
        Bit3：1：微信提醒使能，0：微信提醒关闭
        Bit4：1：Facebook提醒使能，0：Facebook提醒关闭
        Bit5：1：WhatsApp提醒使能，0：WhatsApp提醒关闭
        Bit6：1：Twitter提醒使能，0：Twitters提醒关闭
        Bit7：1：Skype提醒使能，0：Skype提醒关闭
        BB:
        bit0: Line
        bit1: Linkedln
        bit2: Instagram
        bit3: TIM
        bit4: Snapchat
        Bit7:	其它APP的提醒开关
         *
         */

        val bean = SetANCSReq()
//        bean.setAllOpen()

        bean.setCall(true)
        bean.setSms(true)
        bean.setQq(true)
        bean.setWechat(true)

        commandHandle.executeReqCmd(bean) { resp ->
            run {

            }
        }
    }


    fun dialIndex(index: Int) {
        // 0自定义 其它市场表盘
        CommandHandle.getInstance()
            .executeReqCmdNoCallback(DialIndexReq.getWriteInstance(index))

        //获取当前表盘序号
        CommandHandle.getInstance()
            .executeReqCmd(
                DialIndexReq.getReadInstance(),
                ICommandResponse<DialIndexRsp> {

                })
    }

    fun batterySaving(open: Boolean) {
        //省电模式开关
        CommandHandle.getInstance()
            .executeReqCmdNoCallback(BatterySavingReq.getWriteInstance(open))

        //读取省电模式
        CommandHandle.getInstance()
            .executeReqCmd(
                BatterySavingReq.getReadInstance(),
                ICommandResponse<BatterySavingRsp> {

                })
    }


    fun heartEnable() {
        // interval  10,15,20,30,60
        CommandHandle.getInstance().executeReqCmd(
            HeartRateSettingReq.getWriteInstance(true, 30),
            ICommandResponse<HeartRateSettingRsp> {

            })
    }

    fun heartWrite() {
        CommandHandle.getInstance().executeReqCmd(
            HeartRateSettingReq.getWriteInstance(
                true,
                10,
                10,
                40,
                110
            ),
            ICommandResponse<HeartRateSettingRsp> {
                Log.d("HeartRateTest", "HeartRateSettingReq Write Success")
            })
    }

    fun heartRead() {
        CommandHandle.getInstance()
            .executeReqCmd(
                HeartRateSettingReq.getReadInstance(),
                ICommandResponse<HeartRateSettingRsp> {
                    Log.d(
                        "HeartRateTest",
                        "HeartRateSettingReq Read isEnable:" + it.isEnable + " startInterval:" + it.startInterval + " tooLowReminder:" + it.tooLowReminder + " tooHighReminder:" + it.tooHighReminder + " mainSwitch:" + it.mainSwitch
                    )
                })
//      //add  Heart rate tooLow/High Reminder Listener
//        BleOperateManager.getInstance()
//            .addOutDeviceListener(ListenerKey.Heart, myDeviceNotifyListener)
    }


     fun palmScreenWrite() {
         // isEnable: whether to display the switch
// isLeft: default left-hand mode (true = left hand, false = right hand)
// light: brightness level, default is 1
// maxLight: maximum brightness, default is 5
// start / end: screen-on and screen-off time
//              Full day: start = 0, end = 0
//              Otherwise, time is the number of minutes since midnight
//              For example, 3:00 AM = 180
        val palmScreen=PalmScreenReq.getWriteInstance(true,true)
         CommandHandle.getInstance().executeReqCmd(palmScreen,ICommandResponse<PalmScreenRsp>{

         })
    }

     fun palmScreenRead() {
         //read
         CommandHandle.getInstance()
             .executeReqCmd(
                 PalmScreenReq.getRingReadInstance(),
                 ICommandResponse<PalmScreenRsp>() {

                 })
    }



    fun registerTempCallback() {
        //注册一次回调
        FileHandle.getInstance().clearCallback()
        FileHandle.getInstance().registerCallback(Callback())
        FileHandle.getInstance().initRegister()
    }

    fun syncAutoTemperature() {
        //同步自动体温3天  0只同步今天 1 同步今天和昨天  2 同步今天昨天和前天 ....最多支持7天
        FileHandle.getInstance().startObtainTemperatureSeries(2)
    }

    fun syncManual() {
        //同步自动体温3天  0只同步今天 1 同步今天和昨天  2 同步今天昨天和前天 ....最多支持7天
        FileHandle.getInstance().startObtainTemperatureOnce(0)
    }

    open inner class Callback : SimpleCallback() {
        //连续体温回调
        override fun onUpdateTemperature(data: TemperatureEntity) {
            Log.i("syncAutoTemperature", "onUpdateTemperature")
        }

        //单次体温回调
        override fun onUpdateTemperatureList(array: MutableList<TemperatureOnceEntity>) {
            Log.i("syncAutoTemperature", "onUpdateTemperatureList")
        }
    }

    companion object {
        var TAG = "Test"
    }

    init {
        commandHandle.executeReqCmd(BindAncsReq()) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //success
            }
        }
        val timeFormatRspIOdmOpResponse = ICommandResponse<UserProfileRsp> { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                if (resultEntity.action == TimeFormatRsp.ACTION_READ) {
                    //success
                } else {
                    //设置成功
                }
            }
        }


        //写
        commandHandle.executeReqCmd(
            TimeFormatReq.getWriteInstance(true, 0.toByte()),
            timeFormatRspIOdmOpResponse
        )
        val bpSettingRspIOdmOpResponse = ICommandResponse<BpSettingRsp> { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                if (resultEntity.action == BpSettingRsp.ACTION_READ) {
                    //读成功
                } else {
                    //写成功
                }
            }
        }


        //Set an alarm that repeats Monday through Saturday at 7:30
        commandHandle.executeReqCmd(
            SetAlarmReq(
                AlarmEntity(
                    1,
                    1,
                    7,
                    30,
                    0x7e.toByte()
                )
            )
        ) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //success
            } else {
                //fail
            }
        }
        commandHandle.executeReqCmd(ReadAlarmReq(1)) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //读取成功
            }
        }

        //Sedentary 9:00 to 18:00, Monday to Saturday, every 60 minutes
        commandHandle.executeReqCmd(
            SetSitLongReq(StartEndTimeEntity(9, 0, 18, 0), 0x7e.toByte(), 60)
        ) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //应答成功
            }
        }
        commandHandle.executeReqCmd(SimpleKeyReq(Constants.CMD_GET_SIT_LONG)) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //读取成功
            }
        }

        //Drink water 7:30 Repeat Monday to Saturday
        commandHandle.executeReqCmd(
            SetDrinkAlarmReq(
                AlarmEntity(
                    1,
                    1,
                    7,
                    30,
                    0x7e.toByte()
                )
            )
        ) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //success
            } else {
                //fail
            }
        }
        commandHandle.executeReqCmd(ReadDrinkAlarmReq(1)) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //success
            }
        }

        //睡眠数据
        commandHandle.executeReqCmd(ReadSleepDetailsReq(1, 0, 95)) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //success
            }
        }

        //当天步数距离kcal
        commandHandle.executeReqCmd(SimpleKeyReq(Constants.CMD_GET_STEP_TODAY)) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //获取数据成功
            }
        }


        //读消息推送开关
        commandHandle.executeReqCmd(SimpleKeyReq(Constants.CMD_GET_ANCS_ON_OFF)) { resultEntity ->
            if (resultEntity.status == BaseRspCmd.RESULT_OK) {
                //获取成功
            }
        }
    }
}

