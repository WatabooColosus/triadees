package local.triade.node;

import android.Manifest;
import android.app.Activity;
import android.content.ContentResolver;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public final class MainActivity extends Activity {
    private static final int REQUEST_IMPORT_LLAMA = 801;
    private static final int REQUEST_IMPORT_MODEL = 802;

    private EditText relayUrl;
    private EditText runtimeUrl;
    private EditText pairingToken;
    private EditText displayName;
    private TextView resourceLimitLabel;
    private TextView status;
    private TextView runtimeStatus;

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
        title.setText("Triade Android Node");
        title.setTextSize(24);
        root.addView(title);

        TextView note = new TextView(this);
        note.setText("Nodo nativo autorizado. Mantiene servicio visible y ejecuta tareas CPU para alimentar la Tríade local/federada.");
        root.addView(note);

        relayUrl = input("Relay URL");
        runtimeUrl = input("8010 Runtime URL");
        pairingToken = input("Pairing token");
        displayName = input("Nombre del dispositivo");
        root.addView(relayUrl);
        root.addView(runtimeUrl);
        root.addView(pairingToken);
        root.addView(displayName);

        resourceLimitLabel = new TextView(this);
        root.addView(resourceLimitLabel);

        Button start = button("Guardar y conectar");
        start.setOnClickListener(v -> startNode());
        root.addView(start);

        Button stop = button("Detener nodo");
        stop.setOnClickListener(v -> stopNode());
        root.addView(stop);

        Button battery = button("Abrir ajuste de batería");
        battery.setOnClickListener(v -> openBatterySettings());
        root.addView(battery);

        Button files = button("Abrir permiso de archivos");
        files.setOnClickListener(v -> openAllFilesSettings());
        root.addView(files);

        Button downloadRuntime = button("Descargar runtime desde 8010");
        downloadRuntime.setOnClickListener(v -> downloadRuntimeFrom8010());
        root.addView(downloadRuntime);

        Button termux = button("Abrir instalador Termux 8010");
        termux.setOnClickListener(v -> openTermuxBootstrap());
        root.addView(termux);

        Button doctor = button("Doctor LLM local");
        doctor.setOnClickListener(v -> showRuntimeDoctor());
        root.addView(doctor);

        Button importLlama = button("Importar llama-cli");
        importLlama.setOnClickListener(v -> openFilePicker(REQUEST_IMPORT_LLAMA));
        root.addView(importLlama);

        Button importModel = button("Importar modelo GGUF");
        importModel.setOnClickListener(v -> openFilePicker(REQUEST_IMPORT_MODEL));
        root.addView(importModel);

        runtimeStatus = new TextView(this);
        root.addView(runtimeStatus);

        status = new TextView(this);
        root.addView(status);
        setContentView(scroll);
    }

    private void loadConfig() {
        NodeConfig config = NodeConfig.load(this);
        relayUrl.setText(config.relayUrl);
        runtimeUrl.setText(config.runtimeUrl);
        pairingToken.setText(config.pairingToken);
        displayName.setText(config.displayName);
        updateResourceLabel();
        status.setText(config.hasIdentity() ? "Nodo guardado: " + config.nodeId : "Sin identidad registrada.");
        showRuntimeDoctor();
    }

    private void startNode() {
        saveCurrentConfig();
        Intent intent = new Intent(this, TriadeNodeService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        status.setText("Servicio iniciado. Revisa la notificación persistente.");
    }

    private void stopNode() {
        Intent intent = new Intent(this, TriadeNodeService.class);
        intent.setAction(TriadeNodeService.ACTION_STOP);
        startService(intent);
        status.setText("Solicitud de detención enviada.");
    }

    private int selectedResourcePercent() {
        return 100;
    }

    private void updateResourceLabel() {
        if (resourceLimitLabel != null) {
            resourceLimitLabel.setText("Modo dedicado: Triade reporta 100% de CPU/RAM disponible. Android conserva limites termicos y de memoria del sistema.");
        }
    }

    private void saveCurrentConfig() {
        NodeConfig.saveUserConfig(
                this,
                relayUrl.getText().toString(),
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

    private void openTermuxBootstrap() {
        saveCurrentConfig();
        String base = cleanBaseUrl(runtimeUrl.getText().toString());
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(base + "/downloads/android/termux-bootstrap.sh"));
        startActivity(intent);
    }

    private void downloadRuntimeFrom8010() {
        saveCurrentConfig();
        status.setText("Descargando runtime desde 8010...");
        new Thread(new Runnable() {
            @Override
            public void run() {
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
                        showRuntimeDoctor();
                    });
                } catch (Exception exc) {
                    runOnUiThread(() -> {
                        status.setText("Descarga runtime fallo: " + exc.getMessage());
                        showRuntimeDoctor();
                    });
                }
            }
        }, "triade-runtime-download").start();
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

    private String cleanBaseUrl(String value) {
        String clean = value == null ? "" : value.trim();
        if (clean.isEmpty()) {
            clean = "http://127.0.0.1:8010";
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

    private void openFilePicker(int requestCode) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        startActivityForResult(intent, requestCode);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }
        Uri uri = data.getData();
        try {
            AndroidModelRuntime runtime = new AndroidModelRuntime(this);
            if (requestCode == REQUEST_IMPORT_LLAMA) {
                File target = new File(runtime.binDir(), "llama-cli");
                copyUriToFile(uri, target);
                target.setExecutable(true, false);
                status.setText("llama-cli importado. El siguiente pulso reportara el backend.");
            } else if (requestCode == REQUEST_IMPORT_MODEL) {
                String name = displayNameForUri(uri);
                if (!name.toLowerCase().endsWith(".gguf")) {
                    throw new IllegalArgumentException("El modelo debe ser .gguf");
                }
                File target = new File(runtime.modelsDir(), safeFileName(name));
                copyUriToFile(uri, target);
                status.setText("Modelo GGUF importado: " + target.getName());
            }
            showRuntimeDoctor();
        } catch (Exception exc) {
            status.setText("Importacion fallo: " + exc.getMessage());
            showRuntimeDoctor();
        }
    }

    private void copyUriToFile(Uri uri, File target) throws Exception {
        ContentResolver resolver = getContentResolver();
        InputStream input = resolver.openInputStream(uri);
        if (input == null) {
            throw new IllegalArgumentException("No se pudo abrir el archivo seleccionado.");
        }
        File parent = target.getParentFile();
        if (parent != null && !parent.exists()) {
            parent.mkdirs();
        }
        try (InputStream in = input; FileOutputStream out = new FileOutputStream(target, false)) {
            byte[] buffer = new byte[1024 * 1024];
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
            }
            out.flush();
        }
    }

    private String displayNameForUri(Uri uri) {
        String name = null;
        try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (index >= 0) {
                    name = cursor.getString(index);
                }
            }
        } catch (Exception ignored) {
        }
        if (name == null || name.trim().isEmpty()) {
            name = "model.gguf";
        }
        return name;
    }

    private String safeFileName(String raw) {
        return raw.replace("\\", "_").replace("/", "_").replace(":", "_").trim();
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
