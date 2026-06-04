package local.triade.node;

import android.content.Context;
import android.content.SharedPreferences;

public final class NodeConfig {
    private static final String PREFS = "triade_node";

    public final String relayUrl;
    public final String runtimeUrl;
    public final String pairingToken;
    public final String displayName;
    public final String nodeId;
    public final String nodeToken;
    public final int resourceLimitPercent;

    private NodeConfig(String relayUrl, String runtimeUrl, String pairingToken, String displayName, String nodeId, String nodeToken, int resourceLimitPercent) {
        this.relayUrl = trimTrailingSlash(relayUrl);
        this.runtimeUrl = trimTrailingSlash(runtimeUrl);
        this.pairingToken = pairingToken;
        this.displayName = displayName;
        this.nodeId = nodeId;
        this.nodeToken = nodeToken;
        this.resourceLimitPercent = clampPercent(resourceLimitPercent);
    }

    public static NodeConfig load(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return new NodeConfig(
                prefs.getString("relayUrl", "https://web-production-8cffa0.up.railway.app"),
                prefs.getString("runtimeUrl", "http://127.0.0.1:8010"),
                prefs.getString("pairingToken", ""),
                prefs.getString("displayName", "Android Node"),
                prefs.getString("nodeId", ""),
                prefs.getString("nodeToken", ""),
                prefs.getInt("resourceLimitPercent", 100)
        );
    }

    public static void saveUserConfig(Context context, String relayUrl, String runtimeUrl, String pairingToken, String displayName, int resourceLimitPercent) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString("relayUrl", trimTrailingSlash(relayUrl))
                .putString("runtimeUrl", trimTrailingSlash(runtimeUrl))
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
