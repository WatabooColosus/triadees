package local.triade.node;

import android.content.Context;
import android.content.SharedPreferences;

public final class NodeConfig {
    private static final String PREFS = "triade_node";

    public final String relayUrl;
    public final String pairingToken;
    public final String displayName;
    public final String nodeId;
    public final String nodeToken;

    private NodeConfig(String relayUrl, String pairingToken, String displayName, String nodeId, String nodeToken) {
        this.relayUrl = trimTrailingSlash(relayUrl);
        this.pairingToken = pairingToken;
        this.displayName = displayName;
        this.nodeId = nodeId;
        this.nodeToken = nodeToken;
    }

    public static NodeConfig load(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return new NodeConfig(
                prefs.getString("relayUrl", "https://web-production-8cffa0.up.railway.app"),
                prefs.getString("pairingToken", ""),
                prefs.getString("displayName", "Android Node"),
                prefs.getString("nodeId", ""),
                prefs.getString("nodeToken", "")
        );
    }

    public static void saveUserConfig(Context context, String relayUrl, String pairingToken, String displayName) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString("relayUrl", trimTrailingSlash(relayUrl))
                .putString("pairingToken", pairingToken.trim())
                .putString("displayName", displayName.trim().isEmpty() ? "Android Node" : displayName.trim())
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
}
