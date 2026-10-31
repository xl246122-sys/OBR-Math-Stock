package com.obrmath.monitor

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SessionStore(context: Context) {
    private val prefs = context.getSharedPreferences("secure_session", Context.MODE_PRIVATE)
    private val alias = "obr-monitor-session-v1"
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    @Synchronized fun save(base: String, token: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val plain = JSONObject().put("base", validatedBase(base)).put("token",token).toString().toByteArray(Charsets.UTF_8)
        val encrypted = cipher.doFinal(plain)
        check(prefs.edit().putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("data", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit()) { "无法保存后台访问设置" }
    }
    @Synchronized fun load(): Pair<String,String>? {
        val data = prefs.getString("data",null) ?: return null
        val iv = prefs.getString("iv",null) ?: return null
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE,key(),GCMParameterSpec(128,Base64.decode(iv,Base64.NO_WRAP)))
        }
        val json = JSONObject(cipher.doFinal(Base64.decode(data,Base64.NO_WRAP)).toString(Charsets.UTF_8))
        return json.getString("base") to json.getString("token")
    }
    @Synchronized fun clear() { check(prefs.edit().clear().commit()) }
}
