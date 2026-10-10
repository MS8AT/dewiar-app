package pro.dewiar.app;

import android.app.Activity;
import android.app.NotificationManager;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Vibrator;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONObject;

/** Окно будильника поверх блокировки (открывает AlarmReceiver): текст крупно, звонок и вибрация, «Понял» и «Отложить
 *  на 10 минут». Звук — выбранный в настройках (Sounds): по кругу, сначала тихо, за 20 секунд — до полной громкости;
 *  уведомление при этом переходит в тихий канал, чтобы не звучать вторым голосом. Звонит 2 минуты, потом смолкает,
 *  окно остаётся. Разметка — кодом, без XML-ресурсов.
 *  «Отложить» ставит новое разовое напоминание через Alarms.put с id вида «<id>-s<секунды>», исходное не трогает. */
public class AlarmActivity extends Activity {
    private Ringtone ring;                          // запасной путь: свой файл не открылся — системная мелодия
    private MediaPlayer player;
    private float vol = 0.25f;
    private Vibrator vib;
    private final Handler h = new Handler();
    private String id, title, kind;

    @SuppressWarnings("deprecation")
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        // флаги окна — для Android до 8.1; новым хватает showWhenLocked/turnScreenOn в AndroidManifest.xml
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD);
        id = getIntent().getStringExtra("id");
        title = getIntent().getStringExtra("title");
        kind = getIntent().getStringExtra("kind");
        if (id == null) { finish(); return; }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(dp(28), dp(40), dp(28), dp(40));
        GradientDrawable bg = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{0xFF1B1530, 0xFF0B0B12, 0xFF231433});
        root.setBackground(bg);
        String who = Faces.name(this, getIntent().getStringExtra("who"));
        android.graphics.Bitmap face = Faces.bitmap(this, getIntent().getStringExtra("who"));
        if (face != null) {                               // кто напоминает — лицо персонажа над временем
            android.widget.ImageView iv = new android.widget.ImageView(this);
            iv.setImageBitmap(face);
            LinearLayout.LayoutParams fl = new LinearLayout.LayoutParams(dp(96), dp(96));
            fl.gravity = Gravity.CENTER_HORIZONTAL;
            fl.bottomMargin = dp(14);
            root.addView(iv, fl);
        }
        TextView head = new TextView(this);
        String what = "alarm".equals(kind) ? "Будильник" : "timer".equals(kind) ? "Таймер" : "Напоминание";
        head.setText(who.isEmpty() ? what : who + " · " + what);
        head.setTextColor(0xFFA9ADC8);
        head.setTextSize(16);
        head.setGravity(Gravity.CENTER);
        head.setLetterSpacing(0.12f);
        TextView clock = new TextView(this);
        clock.setText(new java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault()).format(new java.util.Date()));
        clock.setTextColor(Color.WHITE);
        clock.setTextSize(64);
        clock.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        clock.setGravity(Gravity.CENTER);
        TextView text = new TextView(this);
        text.setText(title == null ? "" : title);
        text.setTextColor(0xFFF2F3FA);
        text.setTextSize(26);
        text.setGravity(Gravity.CENTER);
        text.setPadding(0, dp(18), 0, dp(40));
        Button ok = button("Понял", 0xFF667EEA, 0xFF764BA2);
        Button snooze = button("Отложить на 10 минут", 0x22FFFFFF, 0x22FFFFFF);
        ok.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View v) { done(); } });
        snooze.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View v) { snooze(); } });
        root.addView(head);
        root.addView(clock);
        root.addView(text);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(58));
        lp.bottomMargin = dp(12);
        root.addView(ok, lp);
        root.addView(snooze, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(58)));
        setContentView(root);
        start();
        h.postDelayed(new Runnable() { @Override public void run() { stopSound(); } }, 120000);   // не звонить бесконечно, если человека нет рядом
    }

    private Button button(String t, int c1, int c2) {
        Button b = new Button(this);
        b.setText(t);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setTextSize(17);
        GradientDrawable d = new GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, new int[]{c1, c2});
        d.setCornerRadius(dp(18));
        b.setBackground(d);
        return b;
    }

    private int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density + 0.5f); }

    @SuppressWarnings("deprecation")
    private void start() {
        AlarmReceiver.quiet(this, id, title == null ? "" : title, kind == null ? "reminder" : kind,
                getIntent().getStringExtra("who") == null ? "" : getIntent().getStringExtra("who"));
        player = Sounds.play(this, Sounds.current(this), true, vol);
        if (player != null) {
            h.postDelayed(new Runnable() { @Override public void run() {       // мягко нарастает: не вскакивать от звонка
                if (player == null) return;
                vol = Math.min(1f, vol + 0.0375f);
                try { player.setVolume(vol, vol); } catch (Throwable ignored) { }
                if (vol < 1f) h.postDelayed(this, 1000);
            } }, 1000);
        } else try {
            android.net.Uri u = Sounds.uri(this, "system");
            ring = RingtoneManager.getRingtone(this, u);
            if (ring != null) {
                ring.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
                if (Build.VERSION.SDK_INT >= 28) {         // повтор мелодии — с Android 9, отражением (собираем против API 23)
                    try { Ringtone.class.getMethod("setLooping", boolean.class).invoke(ring, true); } catch (Throwable ignored) { }
                }
                ring.play();
            }
        } catch (Throwable ignored) { }
        try {
            vib = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (vib != null) vib.vibrate(new long[]{0, 400, 900, 400, 2400}, 0);   // два мягких толчка и пауза, по кругу
        } catch (Throwable ignored) { }
    }

    private void stopSound() {
        try { if (ring != null) ring.stop(); } catch (Throwable ignored) { }
        try { if (player != null) { player.stop(); player.release(); } } catch (Throwable ignored) { }
        player = null;
        try { if (vib != null) vib.cancel(); } catch (Throwable ignored) { }
    }

    private void done() {
        stopSound();
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).cancel(id.hashCode());
        finish();
    }

    private void snooze() {
        try {
            JSONObject x = new JSONObject().put("id", id + "-s" + (System.currentTimeMillis() / 1000)).put("title", title)
                    .put("kind", kind).put("repeat", "").put("at", System.currentTimeMillis() + 10 * 60000L)
                    .put("who", String.valueOf(getIntent().getStringExtra("who") == null ? "" : getIntent().getStringExtra("who")));
            Alarms.put(this, x);
        } catch (Exception ignored) { }
        done();
    }

    @Override protected void onDestroy() { stopSound(); h.removeCallbacksAndMessages(null); super.onDestroy(); }
}
