package local.triade.node;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

public final class MainActivity extends Activity {
    private TextView status;
    private TextView runtimeStatus;
    private TextView liveLog;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        requestNotificationPermission();
        autoStart();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(18);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("Triade Node · Auto 8010");
        title.setTextSize(24);
        root.addView(title);

        TextView note = new TextView(this);
        note.setText("Modo automatico: conecta directo al 8010 local/dominio, registra el nodo, mantiene heartbeat y toma jobs en segundo plano. Sin relay por defecto.");
        root.addView(note);

        status = new TextView(this);
        root.addView(status);

        runtimeStatus = new TextView(this);
        root.addView(runtimeStatus);

        liveLog = new TextView(this);
        liveLog.setText("Pulso:\n");
        root.addView(liveLog);
        setContentView(scroll);
    }

    private void autoStart() {
        NodeConfig config = NodeConfig.load(this);
        appendLog("Endpoint directo: " + config.relayUrl);
        appendLog("Runtime assets: " + config.runtimeUrl);
        status.setText("Conectando automaticamente con Tríade 8010...");
        testHealthAndStart();
    }

    private void testHealthAndStart() {
        new Thread(() -> {
            try {
                NodeConfig config = NodeConfig.load(MainActivity.this);
                String body = getText(config.relayUrl + "/health");
                runOnUiThread(() -> {
                    appendLog("Health OK: " + trimForLog(body));
                    status.setText("8010 disponible. Activando worker...");
                });
                autoSetupRuntimeIfAvailable();
                startNodeService();
                sendHeartbeatOnce();
            } catch (Exception exc) {
                runOnUiThread(() -> {
                    status.setText("No se pudo conectar al 8010: " + exc.getMessage());
                    appendLog("Error conexion: " + exc.getMessage());
                    appendLog("Verifica que el PC corra uvicorn --host 0.0.0.0 --port 8010 y que la IP sea alcanzable.");
                });
            }
        }, "triade-auto-start").start();
    }

    private void startNodeService() {
        Intent intent = new Intent(this, TriadeNodeService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        runOnUiThread(() -> appendLog("Worker en segundo plano iniciado."));
    }

    private void sendHeartbeatOnce() {
        new Thread(() -> {
            try {
                RelayClient client = new RelayClient(MainActivity.this);
                NodeConfig config = client.ensureRegistered();
                client.heartbeat(config);
                runOnUiThread(() -> {
                    status.setText("Nodo activo: " + config.nodeId);
                    appendLog("Heartbeat OK: " + config.nodeId);
                    showRuntimeDoctor();
                });
            } catch (Exception exc) {
                runOnUiThread(() -> {
                    status.setText("Heartbeat fallo: " + exc.getMessage());
                    appendLog("Heartbeat fallo: " + exc.getMessage());
                });
            }
        }, "triade-heartbeat-once").start();
    }

    private void autoSetupRuntimeIfAvailable() {
        try {
            NodeConfig config = NodeConfig.load(this);
            String manifest = getText(config.runtimeUrl + "/downloads/android/runtime-manifest");
            appendLog("Manifest runtime: " + trimForLog(manifest));
            if (!manifest.contains("\"status\":\"ok\"") && !manifest.contains("\"status\": \"ok\"")) {
                appendLog("Runtime pesado no disponible en 8010. Worker queda activo para jobs CPU/preproceso.");
                return;
            }
            AndroidModelRuntime runtime = new AndroidModelRuntime(this);
            File llama = new File(runtime.binDir(), "llama-cli");
            File model = new File(runtime.modelsDir(), "triade-base.gguf");
            if (!llama.exists()) {
                downloadUrlToFile(config.runtimeUrl + "/downloads/android/llama-cli", llama);
                llama.setExecutable(true, false);
                appendLog("llama-cli instalado.");
            }
            if (!model.exists()) {
                downloadUrlToFile(config.runtimeUrl + "/downloads/android/base-model.gguf", model);
                appendLog("GGUF base instalado.");
            }
            appendLog("Runtime local configurado.");
        } catch (Exception exc) {
            appendLog("Auto runtime omitido: " + exc.getMessage());
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 40);
        }
        try {
            if (Build.VERSION.SDK_INT >= 23) {
                Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivity(intent);
            }
        } catch (Exception ignored) {
        }
    }

    private void downloadUrlToFile(String url, File target) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(120000);
        conn.setRequestMethod("GET");
        int code = conn.getResponseCode();
        if (code >= 400) {
            throw new IllegalStateException("HTTP " + code + " en " + url);
        }
        File parent = target.getParentFile();
        if (parent != null && !parent.exists()) {
            parent.mkdirs();
        }
        try (InputStream in = conn.getInputStream(); FileOutputStream out = new FileOutputStream(target, false)) {
            byte[] buffer = new byte[1024 * 1024];
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
            }
            out.flush();
        } finally {
            conn.disconnect();
        }
    }

    private String getText(String url) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(15000);
        conn.setRequestMethod("GET");
        int code = conn.getResponseCode();
        BufferedReader reader = new BufferedReader(new InputStreamReader(code >= 400 ? conn.getErrorStream() : conn.getInputStream(), "UTF-8"));
        StringBuilder builder = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            builder.append(line);
        }
        conn.disconnect();
        if (code >= 400) {
            throw new IllegalStateException("HTTP " + code + ": " + builder);
        }
        return builder.toString();
    }

    private void showRuntimeDoctor() {
        try {
            AndroidModelRuntime runtime = new AndroidModelRuntime(this);
            runtimeStatus.setText(runtime.doctor().toString(2));
        } catch (Exception exc) {
            runtimeStatus.setText("Doctor LLM fallo: " + exc.getMessage());
        }
    }

    private void appendLog(String text) {
        runOnUiThread(() -> {
            if (liveLog != null) {
                liveLog.append("\n• " + text);
            }
        });
    }

    private String trimForLog(String text) {
        if (text == null) {
            return "";
        }
        return text.length() > 180 ? text.substring(0, 180) + "..." : text;
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density);
    }
}
