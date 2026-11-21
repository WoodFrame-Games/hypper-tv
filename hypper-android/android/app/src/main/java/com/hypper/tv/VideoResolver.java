package com.hypper.tv;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Превращает ссылку (YouTube / прямой mp4) в ссылку на реальный видеопоток
 * и умеет скачать его в кэш, чтобы кадры читались с диска.
 *
 * YouTube: android-клиент youtubei/v1/player отдаёт обычный mp4 (itag 18)
 * без подписи и без «торможения» первых мегабайт.
 */
public final class VideoResolver {

    public interface Log {
        void line(String msg);
    }

    public static final class Candidate {
        public final String url;
        public final String userAgent;
        public final String label;

        Candidate(String url, String userAgent, String label) {
            this.url = url;
            this.userAgent = userAgent;
            this.label = label;
        }
    }

    /** Клиент YouTube, который отдаёт mp4 без ограничения по байтам. */
    private static final String ANDROID_VER = "20.10.38";
    private static final String ANDROID_UA =
            "com.google.android.youtube/" + ANDROID_VER + " (Linux; U; Android 11) gzip";
    /** Запасной клиент (mp4-DASH, читается только с начала). */
    private static final String IOS_VER = "20.10.4";
    private static final String IOS_UA =
            "com.google.ios.youtube/" + IOS_VER + " (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)";

    private static final String PLAYER_URL =
            "https://www.youtube.com/youtubei/v1/player?prettyPrint=false";

    private static final Pattern[] ID_PATTERNS = {
            Pattern.compile("[?&]v=([A-Za-z0-9_-]{11})"),
            Pattern.compile("youtu\\.be/([A-Za-z0-9_-]{11})"),
            Pattern.compile("youtube\\.com/shorts/([A-Za-z0-9_-]{11})"),
            Pattern.compile("youtube\\.com/embed/([A-Za-z0-9_-]{11})"),
            Pattern.compile("youtube\\.com/live/([A-Za-z0-9_-]{11})"),
    };

    private VideoResolver() {
    }

    /** Возвращает список кандидатов в порядке предпочтения (первый — лучший). */
    public static List<Candidate> resolve(String input, Log log) {
        List<Candidate> out = new ArrayList<>();
        String videoId = youTubeId(input);
        if (videoId == null) {
            log.line("ссылка прямая, качаю как есть");
            out.add(new Candidate(input, "Mozilla/5.0", "прямая ссылка"));
            return out;
        }
        log.line("YouTube id: " + videoId + " — получаю прямой поток");
        for (String client : new String[]{"android", "ios"}) {
            try {
                String body = playerResponse(videoId, client, log);
                if (body == null) {
                    continue;
                }
                JSONObject j = new JSONObject(body);
                JSONObject ps = j.optJSONObject("playabilityStatus");
                String status = ps == null ? "" : ps.optString("status");
                if (!"OK".equals(status)) {
                    log.line("YouTube (" + client + "): " + status + " "
                            + (ps == null ? "" : ps.optString("reason")));
                    continue;
                }
                JSONObject sd = j.optJSONObject("streamingData");
                if (sd == null) {
                    continue;
                }
                String ua = "android".equals(client) ? ANDROID_UA : IOS_UA;
                addAll(out, collect(sd.optJSONArray("formats")), ua, "mp4", log);
                addAll(out, mp4Only(collect(sd.optJSONArray("adaptiveFormats"))),
                        ua, "mp4 (видео)", log);
                if (!out.isEmpty()) {
                    break;
                }
            } catch (Throwable e) {
                log.line("YouTube (" + client + "): ошибка разбора " + e);
            }
        }
        if (out.isEmpty()) {
            log.line("YouTube: не нашёл mp4-поток");
        }
        return out;
    }

    private static List<JSONObject> collect(JSONArray arr) {
        List<JSONObject> out = new ArrayList<>();
        if (arr == null) {
            return out;
        }
        for (int i = 0; i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o != null && o.optString("url").length() > 0) {
                out.add(o);
            }
        }
        return out;
    }

    private static List<JSONObject> mp4Only(List<JSONObject> list) {
        List<JSONObject> out = new ArrayList<>();
        for (JSONObject f : list) {
            if (f.optString("mimeType").startsWith("video/mp4")) {
                out.add(f);
            }
        }
        return out;
    }

    private static void addAll(List<Candidate> out, List<JSONObject> list, String ua, String kind,
                               Log log) {
        List<JSONObject> sorted = new ArrayList<>(list);
        sorted.sort((a, b) -> score(b) - score(a));
        for (JSONObject f : sorted) {
            String url = f.optString("url");
            if (url.isEmpty()) {
                continue;
            }
            boolean dup = false;
            for (Candidate c : out) {
                if (c.url.equals(url)) {
                    dup = true;
                    break;
                }
            }
            if (dup) {
                continue;
            }
            String label = kind + " itag=" + f.optInt("itag")
                    + " " + f.optString("qualityLabel", "?");
            out.add(new Candidate(url, ua, label));
            log.line("поток: " + label);
        }
    }

    private static int score(JSONObject f) {
        Matcher m = Pattern.compile("(\\d+)p").matcher(f.optString("qualityLabel"));
        int h = 0;
        if (m.find()) {
            try {
                h = Integer.parseInt(m.group(1));
            } catch (Exception ignored) {
            }
        }
        // muxed mp4 (обычный, без отдельного звука) — в приоритете
        if (f.optString("mimeType").contains("mp4a")) {
            return 200 + (h == 360 ? 10 : 0);
        }
        if (h == 360) {
            return 100;
        }
        if (h == 480) {
            return 90;
        }
        if (h == 240) {
            return 80;
        }
        if (h == 144) {
            return 70;
        }
        return 10;
    }

    public static String youTubeId(String input) {
        if (input == null) {
            return null;
        }
        String s = input.trim();
        if (!s.contains("youtu")) {
            return null;
        }
        for (Pattern p : ID_PATTERNS) {
            Matcher m = p.matcher(s);
            if (m.find()) {
                return m.group(1);
            }
        }
        return null;
    }

    private static String playerResponse(String videoId, String client, Log log) {
        boolean ios = "ios".equals(client);
        String ver = ios ? IOS_VER : ANDROID_VER;
        String ua = ios ? IOS_UA : ANDROID_UA;
        HttpURLConnection c = null;
        try {
            JSONObject ctx = new JSONObject()
                    .put("clientName", ios ? "IOS" : "ANDROID")
                    .put("clientVersion", ver)
                    .put("hl", "en")
                    .put("gl", "US")
                    .put("userAgent", ua);
            if (ios) {
                ctx.put("deviceMake", "Apple").put("deviceModel", "iPhone16,2")
                        .put("osName", "iPhone").put("osVersion", "18.3.2.22D82");
            } else {
                ctx.put("androidSdkVersion", 33).put("osName", "Android").put("osVersion", "13")
                        .put("deviceMake", "Google").put("deviceModel", "Pixel 7");
            }
            JSONObject body = new JSONObject()
                    .put("context", new JSONObject().put("client", ctx))
                    .put("videoId", videoId)
                    .put("contentCheckOk", true)
                    .put("racyCheckOk", true);

            c = (HttpURLConnection) new URL(PLAYER_URL).openConnection();
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setConnectTimeout(15000);
            c.setReadTimeout(25000);
            c.setRequestProperty("Content-Type", "application/json");
            c.setRequestProperty("User-Agent", ua);
            c.setRequestProperty("Accept-Language", "en-US,en;q=0.9");
            if (!ios) {
                c.setRequestProperty("X-Goog-Api-Format-Version", "1");
                c.setRequestProperty("X-YouTube-Client-Name", "3");
                c.setRequestProperty("X-YouTube-Client-Version", ANDROID_VER);
            }
            try (OutputStream os = c.getOutputStream()) {
                os.write(body.toString().getBytes("UTF-8"));
            }
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            if (in == null) {
                log.line("YouTube: HTTP " + code);
                return null;
            }
            StringBuilder sb = new StringBuilder();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) {
                sb.append(new String(buf, 0, n, "UTF-8"));
            }
            in.close();
            log.line("YouTube (" + client + "): ответ " + code + " (" + sb.length() + " симв.)");
            return sb.toString();
        } catch (Throwable e) {
            log.line("YouTube (" + client + "): сеть недоступна (" + e + ")");
            return null;
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }

    /** Reuse a complete cached download only when it belongs to this exact input URL. */
    public static File cached(File dir, String source, Log log) {
        File dst = new File(dir, "stream.mp4");
        File marker = new File(dir, "stream.source");
        if (!dst.isFile() || dst.length() < 65536 || !marker.isFile()) {
            return null;
        }
        try (InputStream in = new FileInputStream(marker)) {
            byte[] bytes = new byte[(int) Math.min(marker.length(), 8192)];
            int n = in.read(bytes);
            String saved = n <= 0 ? "" : new String(bytes, 0, n, "UTF-8");
            if (saved.equals(source.trim())) {
                log.line("видео: использую кэш (" + (dst.length() / 1048576) + " МБ)");
                return dst;
            }
        } catch (Throwable e) {
            log.line("видео: не удалось проверить кэш: " + e);
        }
        return null;
    }

    /**
     * Скачивает поток в файл в кэше, читая блоками с явными диапазонами:
     * без Range сервер отвечает 403.
     * Возвращает null, если файл слишком большой или не скачался.
     */
    public static File download(Candidate cand, File dir, long maxBytes, String source, Log log) {
        File tmp = new File(dir, "stream.mp4.part");
        File dst = new File(dir, "stream.mp4");
        final long chunk = 2L * 1024 * 1024;
        long pos = 0;
        long total = -1;
        long nextLog = 8L * 1024 * 1024;
        try (OutputStream os = new FileOutputStream(tmp)) {
            byte[] buf = new byte[65536];
            while (true) {
                HttpURLConnection c = null;
                try {
                    c = (HttpURLConnection) new URL(cand.url).openConnection();
                    c.setConnectTimeout(15000);
                    c.setReadTimeout(30000);
                    c.setRequestProperty("User-Agent", cand.userAgent);
                    c.setRequestProperty("Referer", "https://www.youtube.com/");
                    c.setRequestProperty("Range", "bytes=" + pos + "-" + (pos + chunk - 1));
                    int code = c.getResponseCode();
                    if (code != 200 && code != 206) {
                        log.line("загрузка: HTTP " + code + " на байте " + pos);
                        return null;
                    }
                    if (total < 0) {
                        total = parseTotal(c.getHeaderField("Content-Range"),
                                c.getContentLengthLong());
                        if (total > maxBytes) {
                            log.line("загрузка: файл " + (total / 1048576)
                                    + " МБ — больше лимита, играю потоком");
                            return null;
                        }
                        if (total > 0) {
                            log.line("загрузка: всего " + (total / 1048576) + " МБ");
                        }
                    }
                    InputStream in = c.getInputStream();
                    int n;
                    long got = 0;
                    while ((n = in.read(buf)) > 0) {
                        os.write(buf, 0, n);
                        pos += n;
                        got += n;
                        if (pos > maxBytes) {
                            log.line("загрузка: превышен лимит");
                            return null;
                        }
                        if (pos >= nextLog) {
                            log.line("загрузка: " + (pos / 1048576) + " МБ"
                                    + (total > 0 ? " из " + (total / 1048576) : ""));
                            nextLog += 8L * 1024 * 1024;
                        }
                        if (!MainActivity.isPumping() || !MainActivity.isWorkerRunning()) {
                            log.line("загрузка: отменено (поток комнаты завершён)");
                            return null;
                        }
                    }
                    in.close();
                    if (got == 0) {
                        break;
                    }
                } finally {
                    if (c != null) {
                        c.disconnect();
                    }
                }
                if (total > 0 && pos >= total) {
                    break;
                }
            }
            log.line("загрузка: готово " + (pos / 1024) + " КБ");
            if (pos < 65536) {
                return null;
            }
        } catch (Throwable e) {
            log.line("загрузка: ошибка " + e);
            return null;
        }
        if (dst.exists() && !dst.delete()) {
            log.line("загрузка: не смог переписать кэш");
        }
        if (!tmp.renameTo(dst)) {
            log.line("загрузка: не смог переименовать файл");
            return null;
        }
        File markerTmp = new File(dir, "stream.source.part");
        File marker = new File(dir, "stream.source");
        try (OutputStream out = new FileOutputStream(markerTmp)) {
            out.write(source.trim().getBytes("UTF-8"));
        } catch (Throwable e) {
            log.line("кэш: не удалось сохранить источник: " + e);
            return dst;
        }
        if (marker.exists()) {
            marker.delete();
        }
        if (!markerTmp.renameTo(marker)) {
            log.line("кэш: не удалось сохранить метку источника");
        }
        return dst;
    }

    private static long parseTotal(String contentRange, long contentLength) {
        if (contentRange != null) {
            int slash = contentRange.lastIndexOf('/');
            if (slash > 0) {
                try {
                    return Long.parseLong(contentRange.substring(slash + 1).trim());
                } catch (Exception ignored) {
                }
            }
        }
        return contentLength;
    }
}
