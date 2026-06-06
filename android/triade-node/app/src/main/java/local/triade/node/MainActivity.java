package local.triade.node;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.Button;
import android.widget.EditText;
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
    private EditText directUrl;
    private EditText runtimeUrl;
    private EditText pairingToken;
    private EditText displayName;
    private TextView resourceLimitLabel;
    private TextView status;
    private TextView runtimeStatus;
    private TextView liveLog;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        loadConfig();
        requestNotificationPermission();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(18);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("Triade Node · Direct 8010");
        title.setTextSize(24);
        root.addView(title);

        TextView note = new TextView(this);
        note.setText("Worker Android local. Se conecta directo al 8010 por LAN o dominio publico, sin relay por defecto. Ejecuta heartbeat, jobs sandbox y transfiere resultados en segundo plano.");
        root.addView(note);

        directUrl = input("URL directa 8010 o dominio");
        runtimeUrl = input("Runtime 8010 para assets/modelos");
        pairingToken = input("Clave / pairing token opcional");
        displayName = input("Nombre del dispositivo");
        root.addView(directUrl);
        root.addView(runtimeUrl);
        root.addView(pairingToken);
        root.addView(displayName);

        resourceLimitLabel = new TextView(this);
        root.addView(resourceLimitLabel);

        Button health = button("Test Health 8010");
        health.setOnClickListener(v -> testHealth());
        root.addView(health);

        Button start = button("Guardar, registrar y activar worker");
        start.setOnClickListener(v -> startNode());
        root.addView(start);

        Button heartbeat = button("Enviar heartbeat ahora");
        heartbeat.setOnClickListener(v -> sendHeartbeatOnce());
        root.addView(heartbeat);

        Button stop = button("Detener worker");
        stop.setOnClickListener(v -> stopNode());
        root.addView(stop);

        Button battery = button("Permitir segundo plano / bateria");
        battery.setOnClickListener(v -> openBatterySettings());
        root.addView(battery);

        Button files = button("Permiso archivos para GGUF/runtime");
        files.setOnClickListener(v -> openAllFilesSettings());
        root.addView(files);

        Button localTest = button("Probar trabajo CPU local");
        localTest.setOnClickListener(v -> runLocalWorkerTest());
        root.addView(localTest);

        Button downloadRuntime = button("Descargar runtime opcional desde 8010");
        downloadRuntime.setOnClickListener(v -> downloadRuntimeFrom8010());
        root.addView(downloadRuntime);

        Button doctor = button("Doctor APK / LLM local");
        doctor.setOnClickListener(v -> showRuntimeDoctor());
        root.addView(doctor);

        runtimeStatus = new TextView(this);
        root.addView(runtimeStatus);

        status = new TextView(this);
        root.addView(status);

        liveLog = new TextView(this);
        liveLog.setText("Logs visibles:\n");
        root.addView(liveLog);
        setContentView(scroll);
    }

    private void loadConfig() {
        NodeConfig config = NodeConfig.load(this);
        directUrl.setText(config.relayUrl);
        runtimeUrl.setText(config.runtimeUrl);
        pairingToken.setText(config.pairingToken);
        displayName.setText(config.displayName);
        updateResourceLabel();
        appendLog(config.hasIdentity() ? "Identidad guardada: " + config.nodeId : "Sin identidad registrada.");
        status.setText(config.hasIdentity() ? "Nodo guardado: " + config.nodeId : "Sin identidad registrada.");
        showRuntimeDoctor();
    }

    private void startNode() {
        saveCurrentConfig();
        appendLog("Iniciando worker directo 8010...");
        Intent intent = new Intent(this, TriadeNodeService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        status.setText("Worker iniciado. Revisa la notificacion persistente y logs de Uvicorn.");
    }

    private void stopNode() {
        Intent intent = new Intent(this, TriadeNodeService.class);
        intent.setAction(TriadeNodeService.ACTION_STOP);
        startService(intent);
        appendLog("Solicitud de detencion enviada.");
        status.setText("Solicitud de detencion enviada.");
    }

    private void testHealth() {
        saveCurrentConfig();
        status.setText("Probando /health...");
        appendLog("GET /health contra " + directUrl.getText());
        new Thread(() -> {
            try {
                String base = cleanBaseUrl(directUrl.getText().toString());
                String body = getText(base + "/health");
                runOnUiThread(() -> {
                    status.setText("Health OK: " + base);
                    appendLog("Health OK: " + trimForLog(body));
                });
            } catch (Exception exc) {
                runOnUiThread(() -> {
                    status.setText("Health fallo: " + exc.getMessage());
                    appendLog("Health fallo: " + exc.getMessage());
                });
            }
        }, "triade-health-test").start();
    }

    private void sendHeartbeatOnce() {
        saveCurrentConfig();
        status.setText("Enviando heartbeat manual...");
        new Thread(() -> {
            try {
                RelayClient client = new RelayClient(MainActivity.this);
                NodeConfig config = client.ensureRegistered();
                client.heartbeat(config);
                runOnUiThread(() -> {
                    status.setText("Heartbeat OK: " + config.nodeId);
                    appendLog("Heartbeat OK: " + config.nodeId);
                });
            } catch (Exception exc) {
                runOnUiThread(() -> {
                    status.setText("Heartbeat fallo: " + exc.getMessage());
                    appendLog("Heartbeat fallo: " + exc.getMessage());
                });
            }
        }, "triade-heartbeat-once").start();
    }

    private int selectedResourcePercent() {
        return 100;
    }

    private void updateResourceLabel() {
        if (resourceLimitLabel != null) {
            resourceLimitLabel.setText("Modo dedicado: reporta 100% de CPU/RAM disponible del proceso Android. El sistema conserva limites termicos, bateria y memoria reales.");
        }
    }

    private void saveCurrentConfig() {
        NodeConfig.saveUserConfig(
                this,
                directUrl.getText().toString(),
                runtimeUrl.getText().toString(),
                pairingToken.getText().toString(),
                displayName.getText().toString(),
                selectedResourcePercent()
        );
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 40);
        }
    }

    private void openBatterySettings() {
        try {
            Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
            intent.setData(Uri.parse("package:" + getPackageName()));
            startActivity(intent);
        } catch (Exception ignored) {
            startActivity(new Intent(Settings.ACTION_SETTINGS));
        }
    }

    private void openAllFilesSettings() {
        try {
            if (Build.VERSION.SDK_INT >= 30) {
                Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivity(intent);
            } else {
                startActivity(new Intent(Settings.ACTION_SETTINGS));
            }
        } catch (Exception ignored) {
            startActivity(new Intent(Settings.ACTION_SETTINGS));
        }
    }

    private void downloadRuntimeFrom8010() {
        saveCurrentConfig();
        status.setText("Descargando runtime desde 8010...");
        appendLog("Descargando runtime opcional desde " + runtimeUrl.getText());
        new Thread(() -> {
            try {
                AndroidModelRuntime runtime = new AndroidModelRuntime(MainActivity.this);
                String base = cleanBaseUrl(runtimeUrl.getText().toString());
                File llama = new File(runtime.binDir(), "llama-cli");
                File model = new File(runtime.modelsDir(), "triade-base.gguf");
                StringBuilder report = new StringBuilder();
                downloadUrlToFile(base + "/downloads/android/llama-cli", llama);
                llama.setExecutable(true, false);
                report.append("llama-cli OK\n");
                downloadUrlToFile(base + "/downloads/android/base-model.gguf", model);
                report.append("modelo base OK\n");
                runOnUiThread(() -> {
                    status.setText("Runtime descargado desde 8010:\n" + report.toString());
                    appendLog("Runtime descargado OK.");
                    showRuntimeDoctor();
                });
            } catch (Exception exc) {
                runOnUiThread(() -> {
                    status.setText("Descarga runtime fallo: " + exc.getMessage());
                    appendLog("Descarga runtime fallo: " + exc.getMessage());
                    showRuntimeDoctor();
                });
            }
        }, "triade-runtime-download").start();
    }

    private void runLocalWorkerTest() {
        saveCurrentConfig();
        status.setText("Probando CPU local dentro de la APK...");
        appendLog("Ejecutando benchmark/preprocess local dentro de la APK.");
        new Thread(() -> {
            try {
                RelayClient client = new RelayClient(MainActivity.this);
                JSONObject benchmarkJob = new JSONObject()
                        .put("task", "browser_benchmark")
                        .put("seconds", 1.0)
                        .put("payload", new JSONObject());
                JSONObject preprocessJob = new JSONObject()
                        .put("task", "preprocess_text")
                        .put("payload", new JSONObject()
                                .put("text", "Triade Android Node alimenta el modelo local con trabajo real.")
                                .put("max_chunk_chars", 1200));
                JSONObject benchmark = client.runJob(benchmarkJob);
                JSONObject preprocess = client.runJob(preprocessJob);
                int chunks = preprocess.optJSONArray("chunks") == null ? 0 : preprocess.optJSONArray("chunks").length();
                runOnUiThread(() -> {
                    status.setText("APK ejecuta trabajo real.\nscore=" + benchmark.optLong("score")
                            + "\nwords=" + preprocess.optInt("word_count")
                            + "\nchunks=" + chunks);
                    appendLog("Trabajo local OK: score=" + benchmark.optLong("score") + ", words=" + preprocess.optInt("word_count"));
                });
            } catch (Exception exc) {
                runOnUiThread(() -> {
                    status.setText("Prueba local fallo: " + exc.getMessage());
                    appendLog("Prueba local fallo: " + exc.getMessage());
                });
            }
        }, "triade-local-worker-test").start();
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

    private String cleanBaseUrl(String value) {
        String clean = value == null ? "" : value.trim();
        if (clean.equals("0.0.0.0") || clean.equals("0.0.0.0:8010") || clean.equals("http://0.0.0.0:8010")) {
            clean = NodeConfig.DEFAULT_DIRECT_8010;
        }
        if (clean.isEmpty()) {
            clean = NodeConfig.DEFAULT_DIRECT_8010;
        }
        if (!clean.startsWith("http://") && !clean.startsWith("https://")) {
            clean = "http://" + clean;
        }
        while (clean.endsWith("/")) {
            clean = clean.substring(0, clean.length() - 1);
        }
        return clean;
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
        if (liveLog == null) {
            return;
        }
        liveLog.append("\n• " + text);
    }

    private String trimForLog(String text) {
        if (text == null) {
            return "";
        }
        return text.length() > 180 ? text.substring(0, 180) + "..." : text;
    }

    private EditText input(String hint) {
        EditText edit = new EditText(this);
        edit.setHint(hint);
        edit.setSingleLine(true);
        return edit;
    }

    private Button button(String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        return button;
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density);
    }
}
