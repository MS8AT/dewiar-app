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
    @Override public void onReceive(Context c, Intent in) {
        String id = in.getStringExtra("id");
        if (id == null) return;
        JSONObject x = Alarms.fired(c, id);           // null — в списке уже нет: показываем по данным самого сигнала
        String title = x != null ? x.optString("title", "Напоминание") : in.getStringExtra("title");
        String kind = x != null ? x.optString("kind", "reminder") : "reminder";
        show(c, id, title == null ? "Напоминание" : title, kind, x != null ? x.optString("who", "") : "");
    }

    /** who — персонаж, который ставил напоминание (его лицо и имя — в уведомлении, см. Faces); "" — текущий. */
    static void show(Context c, String id, String title, String kind, String who) {
        Intent full = new Intent(c, AlarmActivity.class).putExtra("id", id).putExtra("title", title).putExtra("kind", kind).putExtra("who", who)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_USER_ACTION);
        PendingIntent fp = PendingIntent.getActivity(c, id.hashCode(), full, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String head = "alarm".equals(kind) ? "⏰ Будильник" : "timer".equals(kind) ? "⏱ Таймер" : "🔔 Напоминание";
        Notification.Builder b = Compat.builder(c, Compat.CH_ALARM);
        String name = Faces.dress(c, b, who);
        // с обликом: заголовок — имя персонажа, вид сигнала — значком в тексте и подписью в шапке (так читается и на часах)
        String text = name.isEmpty() ? title : head.substring(0, head.indexOf(' ')) + " " + title;
        b.setContentTitle(name.isEmpty() ? head : name)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setCategory(Notification.CATEGORY_ALARM)
                .setPriority(Notification.PRIORITY_MAX)
                .setAutoCancel(true)
                .setContentIntent(fp)
                .setFullScreenIntent(fp, true);
        if (!name.isEmpty()) b.setSubText(head.substring(head.indexOf(' ') + 1));
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        nm.notify(id.hashCode(), b.build());
        // приложение на экране — окно сразу; из фона Android 10+ окно не откроет — тогда остаётся уведомление
        try { c.startActivity(full); } catch (Throwable ignored) { }
    }
}
