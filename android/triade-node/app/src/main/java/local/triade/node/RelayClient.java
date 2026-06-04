package local.triade.node;

import android.app.ActivityManager;
import android.content.Context;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public final class RelayClient {
    private final Context context;

    public RelayClient(Context context) {
        this.context = context;
    }

    public NodeConfig ensureRegistered() throws Exception {
        NodeConfig config = NodeConfig.load(context);
        if (config.hasIdentity()) {
            return config;
        }
        JSONObject request = new JSONObject()
                .put("pairing_token", config.pairingToken)
                .put("display_name", config.displayName)
                .put("capabilities", capabilities());
        JSONObject response = post(config.relayUrl + "/api/register", request);
        NodeConfig.saveNodeIdentity(context, response.getString("node_id"), response.getString("node_token"));
        return NodeConfig.load(context);
    }

    public void heartbeat(NodeConfig config) throws Exception {
        JSONObject request = new JSONObject()
                .put("node_id", config.nodeId)
                .put("node_token", config.nodeToken)
                .put("capabilities", capabilities());
        post(config.relayUrl + "/api/heartbeat", request);
    }

    public JSONObject nextJob(NodeConfig config) throws Exception {
        String url = config.relayUrl + "/api/jobs/next?node_id=" + encode(config.nodeId) + "&node_token=" + encode(config.nodeToken);
        return get(url);
    }

    public void submitResult(NodeConfig config, String jobId, String status, JSONObject result, String error) throws Exception {
        JSONObject request = new JSONObject()
                .put("node_id", config.nodeId)
                .put("node_token", config.nodeToken)
                .put("status", status)
                .put("result", result == null ? new JSONObject() : result);
        if (error != null) {
            request.put("error", error);
        }
        post(config.relayUrl + "/api/jobs/" + encode(jobId) + "/result", request);
    }

    public JSONObject runJob(JSONObject job) throws Exception {
        String task = job.getString("task");
        JSONObject payload = job.optJSONObject("payload");
        if (payload == null) {
            payload = new JSONObject();
        }
        if ("echo".equals(task)) {
            return new JSONObject().put("echo", payload);
        }
        if ("sha256".equals(task)) {
            String raw = payload.toString();
            return new JSONObject().put("sha256", TextPreprocessor.sha256(raw)).put("bytes", raw.getBytes("UTF-8").length);
        }
        if ("preprocess_text".equals(task)) {
            return TextPreprocessor.preprocess(payload.optString("text", ""), payload.optInt("max_chunk_chars", 1200));
        }
        if ("federated_inference_probe".equals(task)) {
            return TextPreprocessor.inferenceProbe(payload.optString("prompt", ""), payload.optInt("iterations", 250000));
        }
        if ("android_model_doctor".equals(task)) {
            return new AndroidModelRuntime(context).doctor();
        }
        if ("android_local_generate".equals(task)) {
            return new AndroidModelRuntime(context).generate(payload);
        }
        return benchmark(job.optDouble("seconds", 2.0));
    }

    private JSONObject benchmark(double seconds) throws Exception {
        long end = System.nanoTime() + (long) (seconds * 1_000_000_000L);
        long loops = 0;
        long seed = 1;
        while (System.nanoTime() < end) {
            seed = (seed * 1664525L + 1013904223L) & 0xffffffffL;
            loops += 1;
        }
        return new JSONObject()
                .put("task", "browser_benchmark")
                .put("seconds", seconds)
                .put("loops", loops)
                .put("score", Math.round(loops / seconds))
                .put("seed", seed);
    }

    private JSONObject capabilities() throws Exception {
        NodeConfig config = NodeConfig.load(context);
        ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
        ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
        if (manager != null) {
            manager.getMemoryInfo(memory);
        }
        int cpuTotal = Runtime.getRuntime().availableProcessors();
        int percent = config.resourceLimitPercent;
        int cpuAuthorized = Math.max(1, (int) Math.floor(cpuTotal * (percent / 100.0)));
        double ramAvailableGb = memory.availMem / 1073741824.0;
        double ramAuthorizedGb = ramAvailableGb * (percent / 100.0);
        int memoryClassMb = manager == null ? 0 : manager.getMemoryClass();
        int largeMemoryClassMb = manager == null ? 0 : manager.getLargeMemoryClass();
        Runtime runtime = Runtime.getRuntime();
        double javaHeapMaxGb = runtime.maxMemory() / 1073741824.0;
        double javaHeapFreeGb = runtime.freeMemory() / 1073741824.0;
        double javaHeapTotalGb = runtime.totalMemory() / 1073741824.0;
        JSONArray tasks = new JSONArray()
                .put("echo")
                .put("sha256")
                .put("browser_benchmark")
                .put("preprocess_text")
                .put("federated_inference_probe")
                .put("android_model_doctor")
                .put("android_local_generate");
        JSONObject modelRuntime = new AndroidModelRuntime(context).capabilities();
        return new JSONObject()
                .put("native_android", true)
                .put("app_node", true)
                .put("foreground_service", true)
                .put("background_execution", true)
                .put("resource_limit_percent", percent)
                .put("cpu_count", cpuTotal)
                .put("cpu_authorized_count", cpuAuthorized)
                .put("ram_available_gb", ramAvailableGb)
                .put("ram_authorized_gb", ramAuthorizedGb)
                .put("ram_total_gb", memory.totalMem / 1073741824.0)
                .put("ram_threshold_gb", memory.threshold / 1073741824.0)
                .put("ram_low_memory", memory.lowMemory)
                .put("memory_class_mb", memoryClassMb)
                .put("large_memory_class_mb", largeMemoryClassMb)
                .put("java_heap_max_gb", javaHeapMaxGb)
                .put("java_heap_total_gb", javaHeapTotalGb)
                .put("java_heap_free_gb", javaHeapFreeGb)
                .put("native_large_heap_requested", true)
                .put("platform", "Android " + Build.VERSION.RELEASE)
                .put("device", Build.MANUFACTURER + " " + Build.MODEL)
                .put("app_version", "0.7.0")
                .put("allowed_tasks", tasks)
                .put("edge_model_runtime", modelRuntime.getBoolean("edge_model_runtime"))
                .put("model_runtime_backend", modelRuntime.getString("model_runtime_backend"))
                .put("can_run_local_llm", modelRuntime.getBoolean("can_run_local_llm"))
                .put("local_model_runtime_ready", modelRuntime.getBoolean("local_model_runtime_ready"))
                .put("supported_model_formats", modelRuntime.getJSONArray("supported_model_formats"))
                .put("available_local_models", modelRuntime.getJSONArray("available_local_models"))
                .put("model_runtime_note", modelRuntime.getString("model_runtime_note"));
    }

    private JSONObject get(String url) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("GET");
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(20000);
        return readJson(conn);
    }

    private JSONObject post(String url, JSONObject payload) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(20000);
        conn.setDoOutput(true);
        try (OutputStream output = conn.getOutputStream()) {
            output.write(payload.toString().getBytes("UTF-8"));
        }
        return readJson(conn);
    }

    private JSONObject readJson(HttpURLConnection conn) throws Exception {
        int code = conn.getResponseCode();
        BufferedReader reader = new BufferedReader(new InputStreamReader(
                code >= 400 ? conn.getErrorStream() : conn.getInputStream(), "UTF-8"));
        StringBuilder builder = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            builder.append(line);
        }
        if (code >= 400) {
            throw new IllegalStateException("HTTP " + code + ": " + builder);
        }
        return new JSONObject(builder.toString());
    }

    private static String encode(String value) throws Exception {
        return java.net.URLEncoder.encode(value, "UTF-8");
    }
}
