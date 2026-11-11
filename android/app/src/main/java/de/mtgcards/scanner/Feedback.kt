package de.mtgcards.scanner

import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View

/** Vibration + kurzer Ton als Rückmeldung beim Scannen. */
class Feedback {
    private var tone: ToneGenerator? = null

    private fun generator(): ToneGenerator? {
        if (tone == null) {
            tone = try { ToneGenerator(AudioManager.STREAM_NOTIFICATION, 70) } catch (e: RuntimeException) { null }
        }
        return tone
    }

    fun success(view: View, sound: Boolean) {
        val effect = if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.LONG_PRESS
        view.performHapticFeedback(effect)
        if (sound) generator()?.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
    }

    fun found(view: View) {
        view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
    }

    fun error(view: View, sound: Boolean) {
        val effect = if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.REJECT else HapticFeedbackConstants.LONG_PRESS
        view.performHapticFeedback(effect)
        if (sound) generator()?.startTone(ToneGenerator.TONE_PROP_NACK, 200)
    }

    fun release() {
        tone?.release()
        tone = null
    }
}
