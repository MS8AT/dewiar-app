package pro.dewiar.app;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Голос: синтез речи телефона (Google, Яндекс, RHVoice…) или голос вашего сервера (OpenAI-совместимый /v1/audio/speech).
 *  События в интерфейс: tts_ready {ok} — движок готов (или нет русского), tts_start / tts_done {id} на каждую фразу,
 *  tts_error {id, error} — звук с сервера голоса не получен. tts_done приходит всегда — и при ошибке, и при остановке:
 *  по нему app.js ведёт очередь фраз и понимает, что ассистент договорил. */
public final class Tts {
    private final Context ctx;
    private final Net.Sink sink;
    private TextToSpeech tts;
    private volatile boolean ready;
    private MediaPlayer player;
    private final Object playLock = new Object();    // ожидание конца фразы в play(); stop() будит его, иначе очередь стоит до таймаута
    private java.util.concurrent.ExecutorService queue = java.util.concurrent.Executors.newSingleThreadExecutor();   // фразы сервера — строго по одной
    private volatile int gen;                        // поколение: stop() его меняет, и фразы прежнего поколения не звучат

    public Tts(Context c, Net.Sink sink) {
        this.ctx = c;
        this.sink = sink;
        tts = new TextToSpeech(c, new TextToSpeech.OnInitListener() {
            @Override public void onInit(int status) {
                if (status == TextToSpeech.SUCCESS) {
                    int r = tts.setLanguage(new Locale("ru", "RU"));
                    ready = r != TextToSpeech.LANG_MISSING_DATA && r != TextToSpeech.LANG_NOT_SUPPORTED;
                    tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                        @Override public void onStart(String id) { ev("tts_start", id); }
                        @Override public void onDone(String id) { ev("tts_done", id); }
                        @Override public void onError(String id) { ev("tts_done", id); }
                        @Override public void onStop(String id, boolean interrupted) { ev("tts_done", id); }
                    });
                }
                try { sink.event("tts_ready", new JSONObject().put("ok", ready)); } catch (Exception ignored) { }
            }
        });
    }

    private void ev(String type, String id) {
        try { sink.event(type, new JSONObject().put("id", id)); } catch (Exception ignored) { }
    }

    public boolean ready() { return ready; }

    /** Русские голоса движка: [{name, offline}]. */
    public String voices() {
        JSONArray a = new JSONArray();
        try {
            if (tts != null && tts.getVoices() != null) {
                for (Voice v : tts.getVoices()) {
                    if (v.getLocale() != null && "ru".equals(v.getLocale().getLanguage())) {
                        JSONArray f = new JSONArray();                // у части движков в признаках есть пол голоса
                        if (v.getFeatures() != null) for (String x : v.getFeatures()) f.put(x);
                        a.put(new JSONObject().put("name", v.getName()).put("offline", !v.isNetworkConnectionRequired()).put("features", f));
                    }
                }
            }
        } catch (Throwable ignored) { }
        return a.toString();
    }

    /** Очередь фраз: add=true — дописать к уже звучащему (ответ модели идёт предложениями). */
    public void speak(String id, String text, float rate, float pitch, String voice, boolean add) {
        if (!ready) { ev("tts_done", id); return; }
        try {
            tts.setSpeechRate(rate <= 0 ? 1f : rate);
            tts.setPitch(pitch <= 0 ? 1f : pitch);
            if (voice != null && !voice.isEmpty() && tts.getVoices() != null) {
                for (Voice v : tts.getVoices()) if (v.getName().equals(voice)) { tts.setVoice(v); break; }
            }
            Bundle p = new Bundle();
            p.putString(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, id);
            tts.speak(text, add ? TextToSpeech.QUEUE_ADD : TextToSpeech.QUEUE_FLUSH, p, id);
        } catch (Throwable e) { ev("tts_done", id); }
    }

    public void stop() {
        gen++;                                            // фразы, что ещё в очереди, — не играть
        try { if (tts != null) tts.stop(); } catch (Throwable ignored) { }
        synchronized (this) {
            if (player != null) { try { player.stop(); player.release(); } catch (Throwable ignored) { } player = null; }
        }
        // остановленный плеер onCompletion не шлёт — будим play() сами (не внутри synchronized (this): play() берёт
        // замки в обратном порядке)
        synchronized (playLock) { playLock.notifyAll(); }
    }

    private synchronized boolean playing(MediaPlayer mp) { return player == mp; }

    /** Голос сервера: скачать звук фразы (body — JSON запроса /v1/audio/speech) и проиграть — по одной, по порядку.
     *  Следующая фраза скачивается только после того, как отзвучала предыдущая. */
    public void speakRemote(final String id, final String url, final String key, final String body) {
        final int my = gen;
        queue.execute(new Runnable() {
            @Override public void run() {
                if (my != gen) { ev("tts_done", id); return; }
                try {
                    HttpURLConnection c = (HttpURLConnection) NetProxy.open(new URL(url));
                    c.setConnectTimeout(10000);
                    c.setReadTimeout(60000);
                    c.setRequestMethod("POST");
                    c.setDoOutput(true);
                    c.setRequestProperty("Content-Type", "application/json");
                    if (key != null && key.startsWith("xi-api-key:")) c.setRequestProperty("xi-api-key", key.substring(11));   // ElevenLabs
                    else if (key != null && !key.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + key);
                    OutputStream os = c.getOutputStream();
                    os.write(body.getBytes("UTF-8"));
                    os.close();
                    if (c.getResponseCode() >= 400) throw new Exception("сервер голоса ответил " + c.getResponseCode());
                    File f = new File(ctx.getCacheDir(), "say-" + id + ".audio");
                    InputStream in = c.getInputStream();
                    FileOutputStream fo = new FileOutputStream(f);
                    byte[] buf = new byte[16384];
                    int n;
                    while ((n = in.read(buf)) > 0) fo.write(buf, 0, n);
                    fo.close();
                    in.close();
                    if (my != gen) { f.delete(); ev("tts_done", id); return; }
                    play(id, f);
                } catch (Throwable e) {
                    try { sink.event("tts_error", new JSONObject().put("id", id).put("error", String.valueOf(e.getMessage()))); } catch (Exception ignored) { }
                    ev("tts_done", id);
                }
            }
        });
    }

    /** Проиграть файл и дождаться конца (не дольше 2 минут) в потоке очереди. Звук помечен как голос
     *  ассистента (USAGE_ASSISTANT, Android 8+; на старых — как медиа). */
    private void play(final String id, final File f) throws Exception {
        final Object lock = playLock;
        final boolean[] done = {false};
        MediaPlayer mp = new MediaPlayer();
        mp.setAudioAttributes(new AudioAttributes.Builder().setUsage(android.os.Build.VERSION.SDK_INT >= 26 ? 16 /* USAGE_ASSISTANT */ : AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
        mp.setDataSource(f.getAbsolutePath());
        mp.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
            @Override public void onCompletion(MediaPlayer m) { synchronized (lock) { done[0] = true; lock.notifyAll(); } }
        });
        mp.setOnErrorListener(new MediaPlayer.OnErrorListener() {
            @Override public boolean onError(MediaPlayer m, int a, int b) { synchronized (lock) { done[0] = true; lock.notifyAll(); } return true; }
        });
        mp.prepare();
        synchronized (this) { player = mp; }
        ev("tts_start", id);
        mp.start();
        // ждём конца фразы, остановки (stop() убирает player и будит lock) или 2 минут — на случай, если плеер замолчал без событий
        synchronized (lock) { long end = System.currentTimeMillis() + 120000; while (!done[0] && playing(mp) && System.currentTimeMillis() < end) lock.wait(500); }
        synchronized (this) { if (player == mp) { player = null; } }
        try { mp.release(); } catch (Throwable ignored) { }
        //noinspection ResultOfMethodCallIgnored
        f.delete();
        ev("tts_done", id);
    }

    public void shutdown() {
        stop();
        try { if (tts != null) tts.shutdown(); } catch (Throwable ignored) { }
    }
}
