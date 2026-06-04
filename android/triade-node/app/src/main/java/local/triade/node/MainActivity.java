package local.triade.node;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private EditText relayUrl;
    private EditText pairingToken;
    private EditText displayName;
    private SeekBar resourceLimit;
    private TextView resourceLimitLabel;
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        loadConfig();
        requestNotificationPermission();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(18);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Triade Android Node");
        title.setTextSize(24);
        root.addView(title);

        TextView note = new TextView(this);
        note.setText("Nodo nativo autorizado. Mantiene servicio visible y ejecuta tareas CPU para alimentar la Tríade local/federada.");
        root.addView(note);

        relayUrl = input("Relay URL");
        pairingToken = input("Pairing token");
        displayName = input("Nombre del dispositivo");
        root.addView(relayUrl);
        root.addView(pairingToken);
        root.addView(displayName);

        resourceLimitLabel = new TextView(this);
        root.addView(resourceLimitLabel);
        resourceLimit = new SeekBar(this);
        resourceLimit.setMax(85);
        resourceLimit.setProgress(50);
        resourceLimit.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                updateResourceLabel();
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                saveCurrentConfig();
                status.setText("Recursos actualizados: " + selectedResourcePercent() + "%. El servicio los reportara en el siguiente pulso.");
            }
        });
        root.addView(resourceLimit);

        Button start = button("Guardar y conectar");
        start.setOnClickListener(v -> startNode());
        root.addView(start);

        Button stop = button("Detener nodo");
        stop.setOnClickListener(v -> stopNode());
        root.addView(stop);

        Button battery = button("Abrir ajuste de batería");
        battery.setOnClickListener(v -> openBatterySettings());
        root.addView(battery);

        status = new TextView(this);
        root.addView(status);
        setContentView(root);
    }

    private void loadConfig() {
        NodeConfig config = NodeConfig.load(this);
        relayUrl.setText(config.relayUrl);
        pairingToken.setText(config.pairingToken);
        displayName.setText(config.displayName);
        resourceLimit.setProgress(config.resourceLimitPercent - 10);
        updateResourceLabel();
        status.setText(config.hasIdentity() ? "Nodo guardado: " + config.nodeId : "Sin identidad registrada.");
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
        return resourceLimit.getProgress() + 10;
    }

    private void updateResourceLabel() {
        if (resourceLimitLabel != null && resourceLimit != null) {
            resourceLimitLabel.setText("Recursos autorizados para Triade: " + selectedResourcePercent() + "%");
        }
    }

    private void saveCurrentConfig() {
        NodeConfig.saveUserConfig(
                this,
                relayUrl.getText().toString(),
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
