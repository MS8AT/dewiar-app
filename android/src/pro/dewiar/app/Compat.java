package pro.dewiar.app;

import android.app.Notification;
import android.app.NotificationManager;
import android.content.Context;
import android.media.AudioAttributes;
import android.net.Uri;
import android.os.Build;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;

/** Новые API Android (26+, 31+) — через отражение: tools/build_apk.sh собирает против android.jar API 23, а работать
 *  надо на любых. Здесь каналы уведомлений, Notification.Builder с каналом и проверка права на точные будильники.
 *  Ошибка отражения не роняет приложение — откатываемся к старому поведению. */
public final class Compat {
    // каналы: alarms — будильники и напоминания (важный, звук будильника), info — сообщения ассистента (обычный).
    // Настройки канала Android запоминает при первом создании: поменять звук или важность можно только новым id
    public static final String CH_ALARM = "alarms", CH_INFO = "info";
    private Compat() { }

    public static void channels(Context c) {
        if (Build.VERSION.SDK_INT < 26) return;
        try {
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            Class<?> chc = Class.forName("android.app.NotificationChannel");
            Constructor<?> k = chc.getConstructor(String.class, CharSequence.class, int.class);
            Method create = NotificationManager.class.getMethod("createNotificationChannel", chc);
            Object a = k.newInstance(CH_ALARM, "Будильники и напоминания", 4 /* IMPORTANCE_HIGH */);
            Uri snd = android.media.RingtoneManager.getDefaultUri(android.media.RingtoneManager.TYPE_ALARM);
            AudioAttributes aa = new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
            chc.getMethod("setSound", Uri.class, AudioAttributes.class).invoke(a, snd, aa);
            chc.getMethod("enableVibration", boolean.class).invoke(a, true);
            create.invoke(nm, a);
            Object b = k.newInstance(CH_INFO, "Сообщения ассистента", 3 /* IMPORTANCE_DEFAULT */);
            create.invoke(nm, b);
        } catch (Throwable ignored) { }
    }

    @SuppressWarnings("deprecation")
    public static Notification.Builder builder(Context c, String channel) {
        if (Build.VERSION.SDK_INT >= 26) {
            try {
                return (Notification.Builder) Notification.Builder.class.getConstructor(Context.class, String.class).newInstance(c, channel);
            } catch (Throwable ignored) { }
        }
        return new Notification.Builder(c);
    }

    /** Можно ли ставить точные будильники (Android 12+ спрашивает разрешение; USE_EXACT_ALARM из манифеста даёт его
     *  с Android 13 сразу). Не удалось спросить — считаем, что можно. */
    public static boolean canExact(android.app.AlarmManager am) {
        if (Build.VERSION.SDK_INT < 31) return true;
        try { return (Boolean) android.app.AlarmManager.class.getMethod("canScheduleExactAlarms").invoke(am); }
        catch (Throwable e) { return true; }
    }
}
