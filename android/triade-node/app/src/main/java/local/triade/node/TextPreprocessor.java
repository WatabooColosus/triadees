package local.triade.node;

import org.json.JSONArray;
import org.json.JSONObject;

import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class TextPreprocessor {
    private TextPreprocessor() {
    }

    public static JSONObject preprocess(String text, int maxChunkChars) throws Exception {
        String clean = text == null ? "" : text.replaceAll("\\s+", " ").trim();
        int chunkSize = Math.max(200, Math.min(8000, maxChunkChars));
        String[] rawWords = clean.toLowerCase(Locale.ROOT).split("[^a-záéíóúñü0-9_]+");
        Map<String, Integer> counts = new HashMap<>();
        int wordCount = 0;
        for (String word : rawWords) {
            if (word.length() < 3) {
                continue;
            }
            wordCount += 1;
            counts.put(word, counts.getOrDefault(word, 0) + 1);
        }

        List<Map.Entry<String, Integer>> terms = new ArrayList<>(counts.entrySet());
        Collections.sort(terms, (a, b) -> {
            int byCount = Integer.compare(b.getValue(), a.getValue());
            return byCount != 0 ? byCount : a.getKey().compareTo(b.getKey());
        });

        JSONArray keywords = new JSONArray();
        for (int i = 0; i < Math.min(24, terms.size()); i++) {
            Map.Entry<String, Integer> term = terms.get(i);
            keywords.put(new JSONObject().put("term", term.getKey()).put("count", term.getValue()));
        }

        JSONArray chunks = new JSONArray();
        for (int start = 0; start < clean.length(); start += chunkSize) {
            int end = Math.min(start + chunkSize, clean.length());
            chunks.put(new JSONObject()
                    .put("index", chunks.length())
                    .put("start", start)
                    .put("end", end)
                    .put("text", clean.substring(start, end)));
        }

        return new JSONObject()
                .put("task", "preprocess_text")
                .put("chars", clean.length())
                .put("word_count", wordCount)
                .put("approx_tokens", (int) Math.ceil(wordCount * 1.35))
                .put("sha256", sha256(clean))
                .put("keywords", keywords)
                .put("chunks", chunks);
    }

    public static String sha256(String text) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hash = digest.digest(text.getBytes("UTF-8"));
        StringBuilder builder = new StringBuilder();
        for (byte b : hash) {
            builder.append(String.format("%02x", b));
        }
        return builder.toString();
    }
}
