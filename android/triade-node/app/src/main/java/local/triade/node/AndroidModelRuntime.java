package local.triade.node;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.concurrent.TimeUnit;

public final class AndroidModelRuntime {
    private static final String BACKEND_LLAMA_CPP = "llama.cpp";
    private final Context context;

    public AndroidModelRuntime(Context context) {
        this.context = context;
    }

    public JSONObject doctor() throws Exception {
        JSONArray formats = new JSONArray()
                .put("gguf");
        JSONArray models = modelInventory();
        File executable = llamaExecutable();
        boolean nativeBackendPresent = executable != null && executable.exists() && executable.canExecute();
        boolean canRun = nativeBackendPresent && resolveModel("") != null;
        return new JSONObject()
                .put("task", "android_model_doctor")
                .put("backend", nativeBackendPresent ? BACKEND_LLAMA_CPP : "none")
                .put("native_backend_present", nativeBackendPresent)
                .put("can_run_local_llm", canRun)
                .put("supported_model_formats", formats)
                .put("models_dir", modelsDir().getAbsolutePath())
                .put("backend_dir", binDir().getAbsolutePath())
                .put("backend_executable", executable == null ? "" : executable.getAbsolutePath())
                .put("available_models", models)
                .put("install_contract", installContract())
                .put("note", canRun
                        ? "Backend llama.cpp detectado con modelo GGUF local. Este nodo puede ejecutar android_local_generate."
                        : "Falta instalar un binario nativo llama-cli ejecutable en almacenamiento interno y al menos un modelo .gguf en el directorio models.");
    }

    public JSONObject generate(JSONObject payload) throws Exception {
        String prompt = payload.optString("prompt", "");
        String model = payload.optString("model", "");
        int maxTokens = clamp(payload.optInt("max_tokens", 128), 1, 1024);
        int contextTokens = clamp(payload.optInt("context_tokens", 2048), 256, 8192);
        int threads = clamp(payload.optInt("threads", authorizedThreads()), 1, Runtime.getRuntime().availableProcessors());
        long timeoutSeconds = clamp(payload.optInt("timeout_seconds", 120), 5, 600);
        File executable = llamaExecutable();
        File modelFile = resolveModel(model);
        JSONObject doctor = doctor();
        if (executable == null || !executable.exists() || !executable.canExecute() || modelFile == null) {
            return new JSONObject()
                    .put("task", "android_local_generate")
                    .put("ok", false)
                    .put("status", "unavailable")
                    .put("backend", doctor.getString("backend"))
                    .put("model", model)
                    .put("prompt_sha256", TextPreprocessor.sha256(prompt == null ? "" : prompt))
                    .put("error", "No hay backend nativo listo. Instala llama-cli ejecutable en bin/ y un modelo .gguf en models/.")
                    .put("doctor", doctor);
        }
        ProcessBuilder builder = new ProcessBuilder(
                executable.getAbsolutePath(),
                "-m", modelFile.getAbsolutePath(),
                "-p", prompt == null ? "" : prompt,
                "-n", String.valueOf(maxTokens),
                "-c", String.valueOf(contextTokens),
                "-t", String.valueOf(threads)
        );
        builder.redirectErrorStream(true);
        long started = System.currentTimeMillis();
        final Process process = builder.start();
        final StringBuilder output = new StringBuilder();
        Thread readerThread = new Thread(new Runnable() {
            @Override
            public void run() {
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), "UTF-8"))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        output.append(line).append('\n');
                        if (output.length() > 262144) {
                            break;
                        }
                    }
                } catch (Exception ignored) {
                }
            }
        });
        readerThread.start();
        boolean finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
        if (!finished) {
            process.destroyForcibly();
            readerThread.join(1000);
            return new JSONObject()
                    .put("task", "android_local_generate")
                    .put("ok", false)
                    .put("status", "timeout")
                    .put("backend", BACKEND_LLAMA_CPP)
                    .put("model", modelFile.getName())
                    .put("threads", threads)
                    .put("elapsed_ms", System.currentTimeMillis() - started)
                    .put("prompt_sha256", TextPreprocessor.sha256(prompt == null ? "" : prompt))
                    .put("error", "Tiempo agotado ejecutando llama-cli en Android.");
        }
        readerThread.join(1000);
        int exitCode = process.exitValue();
        return new JSONObject()
                .put("task", "android_local_generate")
                .put("ok", exitCode == 0)
                .put("status", exitCode == 0 ? "completed" : "failed")
                .put("backend", BACKEND_LLAMA_CPP)
                .put("model", modelFile.getName())
                .put("threads", threads)
                .put("max_tokens", maxTokens)
                .put("context_tokens", contextTokens)
                .put("elapsed_ms", System.currentTimeMillis() - started)
                .put("prompt_sha256", TextPreprocessor.sha256(prompt == null ? "" : prompt))
                .put("response", output.toString().trim())
                .put("error", exitCode == 0 ? JSONObject.NULL : "llama-cli termino con codigo " + exitCode)
                .put("doctor", doctor);
    }

    public JSONObject capabilities() throws Exception {
        JSONObject doctor = doctor();
        return new JSONObject()
                .put("edge_model_runtime", true)
                .put("model_runtime_backend", doctor.getString("backend"))
                .put("can_run_local_llm", doctor.getBoolean("can_run_local_llm"))
                .put("local_model_runtime_ready", doctor.getBoolean("can_run_local_llm"))
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

    private JSONObject installContract() throws Exception {
        return new JSONObject()
                .put("backend", BACKEND_LLAMA_CPP)
                .put("binary_names", new JSONArray().put("llama-cli").put("llama-cli-arm64-v8a").put("main"))
                .put("bin_dir", binDir().getAbsolutePath())
                .put("models_dir", modelsDir().getAbsolutePath())
                .put("model_format", "gguf")
                .put("execution", "La APK ejecuta el binario nativo desde almacenamiento interno con ProcessBuilder; Android decide limites finales de memoria/proceso.");
    }

    private File llamaExecutable() {
        File dir = binDir();
        String[] names = new String[]{"llama-cli", "llama-cli-arm64-v8a", "main"};
        for (String name : names) {
            File candidate = new File(dir, name);
            if (candidate.exists()) {
                candidate.setExecutable(true, false);
                return candidate;
            }
        }
        return null;
    }

    private File resolveModel(String requested) {
        File dir = modelsDir();
        if (requested != null && !requested.trim().isEmpty()) {
            File exact = new File(dir, requested.trim());
            if (exact.exists() && exact.isFile()) {
                return exact;
            }
        }
        File[] files = dir.listFiles();
        if (files == null) {
            return null;
        }
        for (File file : files) {
            if (file.isFile() && file.getName().toLowerCase().endsWith(".gguf")) {
                return file;
            }
        }
        return null;
    }

    public File modelsDir() {
        File external = context.getExternalFilesDir("models");
        File dir = external != null ? external : new File(context.getFilesDir(), "models");
        if (!dir.exists()) {
            dir.mkdirs();
        }
        return dir;
    }

    public File binDir() {
        File dir = new File(context.getFilesDir(), "bin");
        if (!dir.exists()) {
            dir.mkdirs();
        }
        return dir;
    }

    private int authorizedThreads() {
        NodeConfig config = NodeConfig.load(context);
        int cpu = Runtime.getRuntime().availableProcessors();
        return Math.max(1, (int) Math.floor(cpu * (config.resourceLimitPercent / 100.0)));
    }

    private static int clamp(int value, int min, int max) {
        return Math.max(min, Math.min(max, value));
    }
}
