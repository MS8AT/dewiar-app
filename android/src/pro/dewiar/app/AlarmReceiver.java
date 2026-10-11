package pro.dewiar.app;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import org.json.JSONObject;

/** Время пришло (сигнал от AlarmManager, поставленный в Alarms.schedule): отметить срабатывание в Alarms.fired
 *  (повтор — на следующий раз, разовое — убрать) и показать уведомление поверх всего с полноэкранным окном будильника
 *  (AlarmActivity) — даже на заблокированном экране. Номер уведомления — id.hashCode(): по нему AlarmActivity его убирает. */
public class AlarmReceiver extends BroadcastReceiver {
    static final String DONE = "pro.dewiar.ALARM_DONE", SNOOZE = "pro.dewiar.ALARM_SNOOZE";

    @Override public void onReceive(Context c, Intent in) {
        String id = in.getStringExtra("id");
        if (id == null) return;
        // кнопки уведомления — на телефоне и на часах (Honor/Huawei, Wear OS и другие повторяют кнопки уведомления)
        if (DONE.equals(in.getAction()) || SNOOZE.equals(in.getAction())) {
            if (SNOOZE.equals(in.getAction())) AlarmActivity.snoozeLater(c, id, in.getStringExtra("title"), in.getStringExtra("kind"), in.getStringExtra("who"));
            ((NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE)).cancel(id.hashCode());
            AlarmActivity.closeIfOpen(id);
            return;
        }
        JSONObject x = Alarms.fired(c, id);           // null — в списке уже нет: показываем по данным самого сигнала
        String title = x != null ? x.optString("title", "Напоминание") : in.getStringExtra("title");
        String kind = x != null ? x.optString("kind", "reminder") : "reminder";
        show(c, id, title == null ? "Напоминание" : title, kind, x != null ? x.optString("who", "") : "");
    }

    /** who — персонаж, который ставил напоминание (его лицо и имя — в уведомлении, см. Faces); "" — текущий. */
    static void show(Context c, String id, String title, String kind, String who) { post(c, id, title, kind, who, true); }

    /** Окно будильника открылось и звучит само: то же уведомление — в канал без звука (звук уведомления смолкает, в шторке
     *  оно остаётся, нажатие снова открывает окно). Канал — важный: часы получают только «важные» уведомления. */
    static void quiet(Context c, String id, String title, String kind, String who) { post(c, id, title, kind, who, false); }

    @SuppressWarnings("deprecation")
    private static void post(Context c, String id, String title, String kind, String who, boolean loud) {
        Intent full = new Intent(c, AlarmActivity.class).putExtra("id", id).putExtra("title", title).putExtra("kind", kind).putExtra("who", who)
                .putExtra("fired", loud ? System.currentTimeMillis() : 0L)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_USER_ACTION);
        PendingIntent fp = PendingIntent.getActivity(c, id.hashCode(), full, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String head = "alarm".equals(kind) ? "⏰ Будильник" : "timer".equals(kind) ? "⏱ Таймер" : "🔔 Напоминание";
        Notification.Builder b = Compat.builder(c, loud ? Sounds.channel(c) : Sounds.quietChannel(c));
        if (loud && android.os.Build.VERSION.SDK_INT < 26) b.setSound(Sounds.uri(c, Sounds.current(c)), Sounds.attrs());   // до Android 8 звук — у самого уведомления
        String name = Faces.dress(c, b, who);
        // с обликом: заголовок — имя персонажа, вид сигнала — значком в тексте и подписью в шапке (так читается и на часах)
        String text = name.isEmpty() ? title : head.substring(0, head.indexOf(' ')) + " " + title;
        b.setContentTitle(name.isEmpty() ? head : name)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setCategory(Notification.CATEGORY_ALARM)
                .setPriority(loud ? Notification.PRIORITY_MAX : Notification.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setOnlyAlertOnce(!loud)
                .setContentIntent(fp);
        if (loud) b.setFullScreenIntent(fp, true);
        b.addAction(action(c, DONE, id, title, kind, who, "Понял"));
        if (!"timer".equals(kind)) b.addAction(action(c, SNOOZE, id, title, kind, who, "Через 10 минут"));
        if (!name.isEmpty()) b.setSubText(head.substring(head.indexOf(' ') + 1));
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        // тихое — обновлением того же уведомления, а не снятием: часы (Honor/Huawei Health) видят одно уведомление,
        // а не «появилось и пропало»; звук уведомления к этому времени уже отзвучал (окно ждёт AlarmActivity.SOUND_DELAY_MS)
        nm.notify(id.hashCode(), b.build());
        if (!loud) return;
        // приложение на экране — окно сразу; из фона Android 10+ окно не откроет — тогда остаётся уведомление
        try { c.startActivity(full); } catch (Throwable ignored) { }
    }

    @SuppressWarnings("deprecation")
    private static Notification.Action action(Context c, String act, String id, String title, String kind, String who, String label) {
        Intent i = new Intent(c, AlarmReceiver.class).setAction(act).putExtra("id", id).putExtra("title", title).putExtra("kind", kind).putExtra("who", who);
        PendingIntent pi = PendingIntent.getBroadcast(c, (act + id).hashCode(), i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Action.Builder(R.drawable.ic_stat, label, pi).build();
    }
}
