package com.rdreh.voice

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build

object BluetoothAudioHelper {
    @Suppress("DEPRECATION")
    fun enableBluetoothMic(ctx: Context) {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val bt = am.availableCommunicationDevices.firstOrNull {
                it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO ||
                    it.type == AudioDeviceInfo.TYPE_BLE_HEADSET
            }
            if (bt != null) am.setCommunicationDevice(bt)
        } else {
            am.startBluetoothSco()
            am.isBluetoothScoOn = true
        }
    }

    @Suppress("DEPRECATION")
    fun disableBluetoothMic(ctx: Context) {
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
