package local.triade.node;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.UUID;

public final class NodeConfig {
    private static final String PREFS = "triade_node";
    public static final String DEFAULT_DIRECT_8010 = "http://192.168.31.135:8010";

    public final String relayUrl;
    public final String runtimeUrl;
    public final String pairingToken;
    public final String displayName;
    public final String nodeId;
    public final String nodeToken;
    public final String publicKey;
    public final int resourceLimitPercent;

    private NodeConfig(String relayUrl, String runtimeUrl, String pairingToken, String displayName, String nodeId, String nodeToken, String publicKey, int resourceLimitPercent) {
        this.relayUrl = trimTrailingSlash(relayUrl);
        this.runtimeUrl = trimTrailingSlash(runtimeUrl);
        this.pairingToken = pairingToken;
        this.displayName = displayName;
        this.nodeId = nodeId;
        this.nodeToken = nodeToken;
        this.publicKey = publicKey;
        this.resourceLimitPercent = clampPercent(resourceLimitPercent);
    }

    public static NodeConfig load(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String publicKey = prefs.getString("publicKey", "");
        if (publicKey == null || publicKey.trim().isEmpty()) {
            publicKey = "android-node-" + UUID.randomUUID();
            prefs.edit().putString("publicKey", publicKey).apply();
        }
        return new NodeConfig(
                prefs.getString("relayUrl", DEFAULT_DIRECT_8010),
                prefs.getString("runtimeUrl", DEFAULT_DIRECT_8010),
                prefs.getString("pairingToken", ""),
                prefs.getString("displayName", "Android Node"),
                prefs.getString("nodeId", ""),
                prefs.getString("nodeToken", ""),
                publicKey,
                prefs.getInt("resourceLimitPercent", 100)
        );
    }

    public static void saveUserConfig(Context context, String relayUrl, String runtimeUrl, String pairingToken, String displayName, int resourceLimitPercent) {
        String cleanDirectUrl = normalizeBaseUrl(relayUrl, DEFAULT_DIRECT_8010);
        String cleanRuntime = normalizeBaseUrl(runtimeUrl, cleanDirectUrl);
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString("relayUrl", cleanDirectUrl)
                .putString("runtimeUrl", cleanRuntime)
                .putString("pairingToken", pairingToken.trim())
                .putString("displayName", displayName.trim().isEmpty() ? "Android Node" : displayName.trim())
                .putInt("resourceLimitPercent", clampPercent(resourceLimitPercent))
                .apply();
    }

    public static void saveNodeIdentity(Context context, String nodeId, String nodeToken) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString("nodeId", nodeId)
                .putString("nodeToken", nodeToken)
                .apply();
    }

    public boolean hasIdentity() {
        return !nodeId.isEmpty() && !nodeToken.isEmpty();
    }

    private static String normalizeBaseUrl(String value, String fallback) {
        String clean = value == null ? "" : value.trim();
        if (clean.equals("0.0.0.0") || clean.equals("0.0.0.0:8010") || clean.equals("http://0.0.0.0:8010")) {
            clean = fallback;
        }
        if (clean.isEmpty()) {
            clean = fallback;
        }
        if (!clean.startsWith("http://") && !clean.startsWith("https://")) {
            clean = "http://" + clean;
        }
        return trimTrailingSlash(clean);
    }

    private static String trimTrailingSlash(String value) {
        String clean = value == null ? "" : value.trim();
        while (clean.endsWith("/")) {
            clean = clean.substring(0, clean.length() - 1);
        }
        return clean;
    }

    private static int clampPercent(int value) {
        if (value < 10) {
            return 10;
        }
        if (value > 100) {
            return 100;
        }
        return value;
    }
}
