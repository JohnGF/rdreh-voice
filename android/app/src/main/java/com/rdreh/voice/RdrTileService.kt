package com.rdreh.voice

import android.content.Intent
import android.service.quicksettings.TileService

class RdrTileService : TileService() {
    override fun onClick() {
        super.onClick()
        val intent = Intent(this, VoiceCaptureActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        }
        startActivityAndCollapse(intent)
    }
}
