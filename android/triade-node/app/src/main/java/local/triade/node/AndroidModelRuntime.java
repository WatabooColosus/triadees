package local.triade.node;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;

public final class AndroidModelRuntime {
    private static final String BACKEND = "none";
    private final Context context;

    public AndroidModelRuntime(Context context) {
        this.context = context;
    }

    public JSONObject doctor() throws Exception {
        JSONArray formats = new JSONArray()
                .put("gguf")
                .put("onnx");
        JSONArray models = modelInventory();
        return new JSONObject()
                .put("task", "android_model_doctor")
                .put("backend", BACKEND)
                .put("native_backend_present", false)
                .put("can_run_local_llm", false)
                .put("supported_model_formats", formats)
                .put("models_dir", modelsDir().getAbsolutePath())
                .put("available_models", models)
                .put("note", "Contrato listo. Falta integrar backend nativo llama.cpp/ONNX para ejecutar modelos reales.");
    }

    public JSONObject generate(JSONObject payload) throws Exception {
        String prompt = payload.optString("prompt", "");
        String model = payload.optString("model", "");
        return new JSONObject()
                .put("task", "android_local_generate")
                .put("ok", false)
                .put("status", "unavailable")
                .put("backend", BACKEND)
                .put("model", model)
                .put("prompt_sha256", TextPreprocessor.sha256(prompt == null ? "" : prompt))
                .put("error", "No hay backend nativo de modelos en la APK. Integrar llama.cpp/ONNX antes de generar tokens en Android.")
                .put("doctor", doctor());
    }

    public JSONObject capabilities() throws Exception {
        JSONObject doctor = doctor();
        return new JSONObject()
                .put("edge_model_runtime", true)
                .put("model_runtime_backend", doctor.getString("backend"))
                .put("can_run_local_llm", doctor.getBoolean("can_run_local_llm"))
                .put("local_model_runtime_ready", doctor.getBoolean("native_backend_present"))
                .put("supported_model_formats", doctor.getJSONArray("supported_model_formats"))
                .put("available_local_models", doctor.getJSONArray("available_models"))
                .put("model_runtime_note", doctor.getString("note"));
    }

    private JSONArray modelInventory() throws Exception {
        JSONArray models = new JSONArray();
        File dir = modelsDir();
        File[] files = dir.listFiles();
        if (files == null) {
            return models;
        }
        for (File file : files) {
            if (!file.isFile()) {
                continue;
            }
            String name = file.getName().toLowerCase();
            if (!(name.endsWith(".gguf") || name.endsWith(".onnx"))) {
                continue;
            }
            models.put(new JSONObject()
                    .put("name", file.getName())
                    .put("path", file.getAbsolutePath())
                    .put("size_mb", Math.round((file.length() / 1048576.0) * 10.0) / 10.0)
                    .put("format", name.endsWith(".gguf") ? "gguf" : "onnx"));
        }
        return models;
    }

    private File modelsDir() {
        File external = context.getExternalFilesDir("models");
        File dir = external != null ? external : new File(context.getFilesDir(), "models");
        if (!dir.exists()) {
            dir.mkdirs();
        }
        return dir;
    }
}
