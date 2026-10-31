package com.obrmath.monitor

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import kotlinx.coroutines.CancellationException
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class FeeWorker(context: Context, params: WorkerParameters): CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        try {
            val saved = SessionStore(applicationContext).load() ?: return Result.success()
            val fees = JSONObject(MonitorApi(saved.first,saved.second).get("fees"))
            val id = feeChangeId(fees) ?: return Result.success()
            val prefs = applicationContext.getSharedPreferences("fee_notifications",Context.MODE_PRIVATE)
            val marker = saved.first+"|"+id
            if (prefs.getString("notified",null)==marker || prefs.getString("acknowledged",null)==marker) return Result.success()
            // A disabled or changed session must not post a late notification.
            if (SessionStore(applicationContext).load()!=saved) return Result.success()
            val manager = applicationContext.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("fee_changes","美股手续费变更",NotificationManager.IMPORTANCE_HIGH))
            if (!manager.areNotificationsEnabled() || manager.getNotificationChannel("fee_changes").importance==NotificationManager.IMPORTANCE_NONE) return Result.success()
            if (Build.VERSION.SDK_INT>=33 && ContextCompat.checkSelfPermission(applicationContext,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED) return Result.success()
            val intent = PendingIntent.getActivity(applicationContext,0,Intent(applicationContext,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            manager.notify(4101,NotificationCompat.Builder(applicationContext,"fee_changes")
                .setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("币安美股手续费发生变更")
                .setContentText("点击查看官方规则及变更前后详情")
                .setContentIntent(intent).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH).build())
            prefs.edit().putString("notified",marker).apply()
            return Result.success()
        } catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { return Result.retry() }
    }
    companion object {
        fun enable(context: Context) {
            val work = PeriodicWorkRequestBuilder<FeeWorker>(15,TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("official_fee_changes",ExistingPeriodicWorkPolicy.UPDATE,work)
        }
        fun disable(context: Context) { WorkManager.getInstance(context).cancelUniqueWork("official_fee_changes") }
    }
}
