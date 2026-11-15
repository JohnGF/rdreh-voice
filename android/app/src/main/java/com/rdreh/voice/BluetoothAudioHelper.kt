package com.rdreh.voice

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build

object BluetoothAudioHelper {
    private var btActive = false

    @Suppress("DEPRECATION")
    fun enableBluetoothMic(ctx: Context) {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val bt = am.availableCommunicationDevices.firstOrNull {
                it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO ||
                    it.type == AudioDeviceInfo.TYPE_BLE_HEADSET
            }
            if (bt != null) {
                am.mode = AudioManager.MODE_IN_COMMUNICATION
                am.setCommunicationDevice(bt)
                btActive = true
            }
        } else if (am.isBluetoothScoAvailableOffCall) {
            val hasBt = am.getDevices(AudioManager.GET_DEVICES_INPUTS).any {
                it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO
            }
            if (hasBt) {
                am.mode = AudioManager.MODE_IN_COMMUNICATION
                am.startBluetoothSco()
                am.isBluetoothScoOn = true
                btActive = true
            }
        }
    }

    @Suppress("DEPRECATION")
    fun disableBluetoothMic(ctx: Context) {
        if (!btActive) return
        btActive = false
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            am.clearCommunicationDevice()
        } else {
            am.isBluetoothScoOn = false
            am.stopBluetoothSco()
        }
        am.mode = AudioManager.MODE_NORMAL
    }
}
