package local.triade.node;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import org.json.JSONObject;

public final class TriadeNodeService extends Service {
    public static final String ACTION_STOP = "local.triade.node.STOP";
    private static final String CHANNEL_ID = "triade-node";
    private volatile boolean running = false;
    private Thread worker;
    private PowerManager.WakeLock wakeLock;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }
        startForeground(10, notification("Conectando nodo Tríade..."));
        if (!running) {
            running = true;
            worker = new Thread(this::loop, "triade-node-loop");
            worker.start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        releaseWakeLock();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void loop() {
        RelayClient client = new RelayClient(this);
        acquireWakeLock();
        while (running) {
            try {
                NodeConfig config = client.ensureRegistered();
                updateNotification("Nodo activo: " + config.nodeId + " - modo dedicado 100%");
                client.heartbeat(config);
                JSONObject next = client.nextJob(config);
                if ("ok".equals(next.optString("status"))) {
                    JSONObject job = next.getJSONObject("job");
                    String jobId = job.getString("job_id");
                    try {
                        JSONObject result = client.runJob(job);
                        client.submitResult(config, jobId, "completed", result, null);
                    } catch (Exception jobError) {
                        client.submitResult(config, jobId, "failed", new JSONObject(), jobError.getMessage());
                    }
                }
                Thread.sleep(3000);
            } catch (Exception error) {
                updateNotification("Nodo esperando: " + error.getMessage());
                sleepQuietly(7000);
            }
        }
    }

    private void acquireWakeLock() {
        try {
            PowerManager manager = (PowerManager) getSystemService(POWER_SERVICE);
            wakeLock = manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "TriadeNode::Worker");
            wakeLock.acquire();
        } catch (Exception ignored) {
            wakeLock = null;
        }
    }

    private void releaseWakeLock() {
        try {
            if (wakeLock != null && wakeLock.isHeld()) {
                wakeLock.release();
            }
        } catch (Exception ignored) {
        }
    }

    private void updateNotification(String text) {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        manager.notify(10, notification(text));
    }

    private Notification notification(String text) {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(new NotificationChannel(CHANNEL_ID, "Triade Node", NotificationManager.IMPORTANCE_LOW));
        }
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        return builder
                .setContentTitle("Triade Node")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_upload)
                .setOngoing(true)
                .build();
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }
}
