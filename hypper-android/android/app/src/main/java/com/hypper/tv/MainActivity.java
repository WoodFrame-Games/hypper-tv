package com.hypper.tv;

import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.media.MediaMetadataRetriever;
import android.os.Bundle;
import android.text.method.ScrollingMovementMethod;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.ViewParent;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.util.HashMap;
import java.util.List;

public class MainActivity extends Activity {

    static {
        System.loadLibrary("hypper_android");
    }

    public native boolean nativeStart(String cfg);

    public native void nativeStop();

    public native boolean nativeIsRunning();

    public native String nativeLogDrain();

    public native void nativePushFrame(byte[] rgb, int w, int h);

    private static TextView logView;
    private static Activity current;
    private static volatile boolean pumping = false;
    private volatile boolean sessionActive = false;

    private EditText room, cols, rows, cellW, cellH, textSize, fps, maxPlayers, password, mode,
            url, startSec, waitSec, cyField;
    private CheckBox patternBox;
    private Button startButton;

    public static void log(String line) {
        // дублируем в logcat — так видно строки приложения через adb
        android.util.Log.i("HypperTV", line);
        final Activity act = current;
        if (act == null || logView == null) {
            return;
        }
        act.runOnUiThread(() -> {
            boolean followTail = isLogAtBottom();
            logView.append(line);
            logView.append("\n");
            if (followTail) {
                logView.post(() -> {
                    if (logView.getLayout() != null) {
                        int contentHeight = logView.getLayout().getHeight()
                                + logView.getPaddingTop() + logView.getPaddingBottom();
                        int maxScroll = Math.max(0, contentHeight - logView.getHeight());
                        logView.scrollTo(0, maxScroll);
                    }
                });
            }
        });
    }

    private static boolean isLogAtBottom() {
        if (logView == null || logView.getLayout() == null) {
            return true;
        }
        int contentHeight = logView.getLayout().getHeight()
                + logView.getPaddingTop() + logView.getPaddingBottom();
        return logView.getScrollY() + logView.getHeight() >= contentHeight - 24;
    }

    static boolean isPumping() {
        return pumping;
    }

    static boolean isWorkerRunning() {
        Activity act = current;
        return act instanceof MainActivity && ((MainActivity) act).nativeIsRunning();
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        current = this;

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(24, 24, 24, 24);
        scroll.addView(root);

        room = field(root, "Комната (можно теги: <color=green>HypperTV</color>)", "HypperTV");
        cols = field(root, "Колонки", "7");
        rows = field(root, "Ряды", "5");
        // Resolution inside a monitor is fixed (18x10 at 50%); the knobs are
        // hidden on purpose - they only make the picture worse.
        cellW = hiddenField("22");
        cellH = hiddenField("12");
        textSize = hiddenField("42");
        fps = field(root, "Кадров/с", "2");
        maxPlayers = field(root, "Игроков (max)", "10");
        password = field(root, "Пароль", "");
        mode = field(root, "Режим (0 Free / 1 Private / 2 Adventure)", "0");
        url = field(root, "Ссылка на видео (YouTube или mp4)", "");
        startSec = field(root, "Старт с секунды", "0");
        waitSec = field(root, "Ждать игрока/загрузку (сек, 0 = сразу)", "20");
        cyField = field(root, "Центр стены по Y (0 = авто)", "0");

        patternBox = new CheckBox(this);
        patternBox.setText("Калибровка: цвет по колонке, яркость по ряду, белый угол слева-сверху");
        patternBox.setTextSize(12f);
        root.addView(patternBox);

        restorePrefs();
        restoreBool("pattern", patternBox);

        // Параметры можно передать интентом (удобно для проверок):
        //   adb shell am start -n com.hypper.tv/.MainActivity \
        //     --es room HypperTV --es password 1234 --es wait 60 \
        //     --es url https://youtu.be/XXX --ez pattern true --ez autostart true
        android.content.Intent it = getIntent();
        applyIntentField(it, "room", room);
        applyIntentField(it, "cols", cols);
        applyIntentField(it, "rows", rows);
        applyIntentField(it, "w", cellW);
        applyIntentField(it, "h", cellH);
        applyIntentField(it, "size", textSize);
        applyIntentField(it, "fps", fps);
        applyIntentField(it, "max", maxPlayers);
        applyIntentField(it, "password", password);
        applyIntentField(it, "mode", mode);
        applyIntentField(it, "url", url);
        applyIntentField(it, "startSec", startSec);
        applyIntentField(it, "wait", waitSec);
        applyIntentField(it, "cy", cyField);
        if (it.hasExtra("pattern")) {
            patternBox.setChecked(it.getBooleanExtra("pattern", false));
        }
        final boolean autoStart = it.getBooleanExtra("autostart", false);

        LinearLayout buttons = new LinearLayout(this);
        startButton = new Button(this);
        startButton.setText("Старт");
        Button stop = new Button(this);
        stop.setText("Стоп");
        buttons.addView(startButton);
        buttons.addView(stop);
        root.addView(buttons);

        TextView hint = new TextView(this);
        hint.setText("Старт создаёт комнату, ждёт входа игрока и завершения загрузки, "
                + "затем строит стену и отправляет кадры. Для проверки зайдите в эту "
                + "комнату из игры на другом устройстве. 0 секунд — без ожидания.");
        hint.setTextSize(12f);
        root.addView(hint);

        logView = new TextView(this);
        logView.setMovementMethod(new ScrollingMovementMethod());
        logView.setTextColor(Color.parseColor("#CCCCCC"));
        logView.setBackgroundColor(Color.parseColor("#101014"));
        logView.setGravity(Gravity.TOP | Gravity.START);
        logView.setPadding(16, 16, 16, 16);
        logView.setTextSize(12f);
        int logHeight = (int) (220 * getResources().getDisplayMetrics().density);
        root.addView(logView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, logHeight));
        logView.setOnTouchListener((v, event) -> {
            ViewParent parent = v.getParent();
            if (parent != null) {
                int action = event.getActionMasked();
                parent.requestDisallowInterceptTouchEvent(
                        action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_MOVE);
            }
            return false;
        });

        startButton.setOnClickListener(v -> {
            if (sessionActive) {
                log("сессия уже запущена; нажмите «Стоп» перед новым запуском");
                return;
            }
            String video = text(url);
            String cfg = "room=" + text(room)
                    + ";cols=" + text(cols)
                    + ";rows=" + text(rows)
                    + ";w=" + text(cellW)
                    + ";h=" + text(cellH)
                    + ";size=" + text(textSize)
                    + ";fps=" + text(fps)
                    + ";max=" + text(maxPlayers)
                    + ";password=" + text(password)
                    + ";mode=" + text(mode)
                    + ";wait=" + text(waitSec)
                    + ";pattern=" + (patternBox.isChecked() ? "1" : "0")
                    + ";video=" + ((!text(url).isEmpty() && !patternBox.isChecked()) ? "1" : "0")
                    + ";cy=" + text(cyField)
                    + ";props=1000;vehicles=40";
            log("запуск: " + cfg);
            savePrefs();
            sessionActive = true;
            startButton.setEnabled(false);
            if (!nativeStart(cfg)) {
                sessionActive = false;
                startButton.setEnabled(true);
                log("не удалось запустить поток");
                return;
            }
            startService(new android.content.Intent(this, PumpService.class));
            if (!video.isEmpty() && !patternBox.isChecked()) {
                startFramePump(video, text(startSec));
            }
        });

        stop.setOnClickListener(v -> {
            pumping = false;
            nativeStop();
            sessionActive = false;
            startButton.setEnabled(true);
            stopService(new android.content.Intent(this, PumpService.class));
            log("стоп");
        });

        setContentView(scroll);

        final android.os.Handler handler = new android.os.Handler(getMainLooper());
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                try {
                    String chunk = nativeLogDrain();
                    if (chunk != null && !chunk.isEmpty()) {
                        for (String line : chunk.split("\n")) {
                            if (!line.isEmpty()) {
                                log(line);
                            }
                        }
                    }
                } catch (Throwable ignored) {
                }
                if (sessionActive && !nativeIsRunning()) {
                    sessionActive = false;
                    pumping = false;
                    if (startButton != null) {
                        startButton.setEnabled(true);
                    }
                    stopService(new android.content.Intent(MainActivity.this, PumpService.class));
                    log("сессия завершилась; можно запустить заново");
                }
                handler.postDelayed(this, 500);
            }
        }, 500);

        if (autoStart) {
            new android.os.Handler(getMainLooper()).postDelayed(
                    () -> startButton.performClick(), 700);
        }
    }

    private void applyIntentField(android.content.Intent it, String key, EditText target) {
        if (it != null && it.hasExtra(key)) {
            String v = it.getStringExtra(key);
            if (v != null) {
                target.setText(v);
            }
        }
    }

    /** Поле, которое не показывается в UI (фиксированный параметр). */
    private EditText hiddenField(String def) {
        EditText e = new EditText(this);
        e.setText(def);
        return e;
    }

    /** Сохранение всех параметров между запусками приложения. */
    private void savePrefs() {
        android.content.SharedPreferences.Editor e =
                getSharedPreferences("hypper_tv", MODE_PRIVATE).edit();
        e.putString("room", text(room));
        e.putString("cols", text(cols));
        e.putString("rows", text(rows));
        e.putString("fps", text(fps));
        e.putString("max", text(maxPlayers));
        e.putString("password", text(password));
        e.putString("mode", text(mode));
        e.putString("url", text(url));
        e.putString("startSec", text(startSec));
        e.putString("wait", text(waitSec));
        e.putString("cy", text(cyField));
        e.putBoolean("pattern", patternBox != null && patternBox.isChecked());
        e.apply();
    }

    private void restorePrefs() {
        android.content.SharedPreferences p = getSharedPreferences("hypper_tv", MODE_PRIVATE);
        restoreField(p, "room", room);
        restoreField(p, "cols", cols);
        restoreField(p, "rows", rows);
        restoreField(p, "fps", fps);
        restoreField(p, "max", maxPlayers);
        restoreField(p, "password", password);
        restoreField(p, "mode", mode);
        restoreField(p, "url", url);
        restoreField(p, "startSec", startSec);
        restoreField(p, "wait", waitSec);
        restoreField(p, "cy", cyField);
    }

    private void restoreField(android.content.SharedPreferences p, String key, EditText target) {
        String v = p.getString(key, null);
        if (v != null) {
            target.setText(v);
        }
    }

    private void restoreBool(String key, android.widget.CheckBox box) {
        box.setChecked(getSharedPreferences("hypper_tv", MODE_PRIVATE)
                .getBoolean(key, false));
    }

    /** Достаём кадры из видео и отдаём в ядро: стена рисует их как текст. */
    private void startFramePump(final String input, final String startSecStr) {
        final float fpsValue;
        try {
            fpsValue = Math.max(0.2f, Float.parseFloat(text(fps)));
        } catch (Exception e) {
            return;
        }
        final int tileW = Math.max(1, Math.min(40, parseInt(text(cellW), 22)));
        final int tileH = Math.max(1, Math.min(24, parseInt(text(cellH), 12)));
        final int wallW = Math.max(1, Math.min(40, parseInt(text(cols), 7))) * tileW;
        final int wallH = Math.max(1, Math.min(25, parseInt(text(rows), 5))) * tileH;
        long sm;
        try {
            sm = (long) (Double.parseDouble(startSecStr) * 1000);
        } catch (Exception e) {
            sm = 0;
        }
        final long startMs = sm;
        pumping = true;
        final File dir = getCacheDir();
        new Thread(() -> {
            VideoResolver.Log log = MainActivity::log;
            log.line("видео: " + input);
            File cached = VideoResolver.cached(dir, input, log);
            if (cached != null) {
                if (playFile(cached, wallW, wallH, fpsValue, startMs, log)) {
                    return;
                }
                log.line("видео: кэш не читается, разрешаю ссылку заново");
            }
            List<VideoResolver.Candidate> cands = VideoResolver.resolve(input, log);
            if (cands.isEmpty()) {
                log.line("видео: поток не получен (ссылка/доступ к YouTube?)");
                return;
            }
            log.line("видео: кандидатов " + cands.size() + ", стена " + wallW + "x" + wallH);

            for (int i = 0; i < cands.size() && i < 4 && pumping; i++) {
                VideoResolver.Candidate c = cands.get(i);
                log.line("пробую: " + c.label);
                File f = VideoResolver.download(c, dir, 300L * 1024 * 1024, input, log);
                if (f != null) {
                    if (playFile(f, wallW, wallH, fpsValue, startMs, log)) {
                        return;
                    }
                    log.line("файл не читается, пробую потоком");
                }
                HashMap<String, String> headers = new HashMap<>();
                headers.put("User-Agent", c.userAgent);
                headers.put("Referer", "https://www.youtube.com/");
                headers.put("Range", "bytes=0-");
                if (playUrl(c.url, headers, wallW, wallH, fpsValue, startMs, log)) {
                    return;
                }
            }
            log.line("видео: все источники не сработали");
        }).start();
    }

    private boolean playFile(final File f, int wallW, int wallH, final float fpsValue,
                             final long startMs, final VideoResolver.Log log) {
        // Fast path: sequential MediaCodec decoding (real-time capable).
        boolean ok = VideoPump.pump(f, wallW, wallH, fpsValue, startMs, new VideoPump.Sink() {
            @Override
            public void push(byte[] rgb, int w, int h) {
                nativePushFrame(rgb, w, h);
            }

            @Override
            public boolean running() {
                return isPumping() && MainActivity.this.nativeIsRunning();
            }

            @Override
            public void line(String s) {
                log.line(s);
            }
        });
        if (ok) {
            return true;
        }
        log.line("видео: MediaCodec не сработал, пробую MediaMetadataRetriever");
        MediaMetadataRetriever r = new MediaMetadataRetriever();
        try {
            r.setDataSource(f.getAbsolutePath());
            return pumpFrames(r, wallW, wallH, fpsValue, startMs, log);
        } catch (Throwable e) {
            log.line("видео: файл — " + e);
            return false;
        } finally {
            try {
                r.release();
            } catch (Throwable ignored) {
            }
        }
    }

    private boolean playUrl(String url, HashMap<String, String> headers, int wallW, int wallH,
                            float fpsValue, long startMs, VideoResolver.Log log) {
        MediaMetadataRetriever r = new MediaMetadataRetriever();
        try {
            r.setDataSource(url, headers);
            return pumpFrames(r, wallW, wallH, fpsValue, startMs, log);
        } catch (Throwable e) {
            log.line("видео: поток — " + e);
            return false;
        } finally {
            try {
                r.release();
            } catch (Throwable ignored) {
            }
        }
    }

    private boolean pumpFrames(MediaMetadataRetriever r, int wallW, int wallH, float fpsValue,
                               long startMs, VideoResolver.Log log) {
        String durStr = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION);
        long durMs = 0;
        try {
            durMs = durStr == null ? 0 : Long.parseLong(durStr);
        } catch (Exception ignored) {
        }
        String wStr = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH);
        String hStr = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT);
        log.line("видео: " + wStr + "x" + hStr + ", " + (durMs / 1000) + " с, "
                + fpsValue + " кадр/с");
        if (durMs <= 0) {
            log.line("видео: длительность неизвестна, читаю по одному кадру");
        }
        long step = (long) (1000 / fpsValue);
        long t = Math.max(0, startMs);
        int sent = 0;
        long startedAt = System.currentTimeMillis();
        Bitmap scaled = null;
        int[] px = new int[wallW * wallH];
        byte[] rgb = new byte[wallW * wallH * 3];
        while (pumping) {
            if (!nativeIsRunning()) {
                log.line("комната закрылась/создание не удалось; останавливаю видео");
                pumping = false;
                if (scaled != null) {
                    scaled.recycle();
                }
                return sent > 0;
            }
            try {
                Bitmap bm = r.getFrameAtTime(t * 1000L, MediaMetadataRetriever.OPTION_CLOSEST);
                if (bm == null) {
                    if (t == 0) {
                        log.line("видео: кадр не декодируется");
                        return false;
                    }
                    t = 0;
                    continue;
                }
                if (scaled == null || scaled.getWidth() != wallW || scaled.getHeight() != wallH) {
                    scaled = Bitmap.createScaledBitmap(bm, wallW, wallH, false);
                } else {
                    android.graphics.Canvas cv = new android.graphics.Canvas(scaled);
                    cv.drawBitmap(bm, new android.graphics.Rect(0, 0, bm.getWidth(), bm.getHeight()),
                            new android.graphics.Rect(0, 0, wallW, wallH), null);
                }
                if (bm != scaled) {
                    bm.recycle();
                }
                scaled.getPixels(px, 0, wallW, 0, 0, wallW, wallH);
                for (int i = 0; i < px.length; i++) {
                    int c = px[i];
                    rgb[i * 3] = (byte) ((c >> 16) & 0xFF);
                    rgb[i * 3 + 1] = (byte) ((c >> 8) & 0xFF);
                    rgb[i * 3 + 2] = (byte) (c & 0xFF);
                }
                nativePushFrame(rgb, wallW, wallH);
                sent++;
                if (sent % 10 == 0) {
                    long sec = Math.max(1, (System.currentTimeMillis() - startedAt) / 1000);
                    log.line("кадров: " + sent + " (" + (sent / sec) + "/с), " + (t / 1000) + " с");
                }
                t += step;
                if (durMs > 0 && t >= durMs) {
                    t = 0;
                }
                Thread.sleep(Math.max(10, step));
            } catch (InterruptedException e) {
                break;
            } catch (Throwable e) {
                log.line("видео: сбой кадра — " + e);
                return sent > 0;
            }
        }
        if (scaled != null) {
            scaled.recycle();
        }
        return true;
    }

    private static int parseInt(String s, int def) {
        try {
            return Integer.parseInt(s.trim());
        } catch (Exception e) {
            return def;
        }
    }

    private EditText field(LinearLayout parent, String label, String value) {
        TextView l = new TextView(this);
        l.setText(label);
        parent.addView(l);
        EditText e = new EditText(this);
        e.setText(value);
        e.setSingleLine(true);
        parent.addView(e);
        return e;
    }

    private String text(EditText e) {
        return e.getText().toString().trim();
    }
}
