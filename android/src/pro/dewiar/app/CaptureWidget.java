package pro.dewiar.app;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.widget.RemoteViews;
import org.json.JSONObject;

/** Значок «Записать» на рабочем столе (отзыв 16.10: «быстро и надёжно закинуть мысль»). Нажатие открывает приложение
 *  с действием pro.dewiar.CAPTURE: app.js слушает, сказанное — в заметки «Идеи» (или напоминание, если «напомни…»),
 *  и приложение уходит обратно на рабочий стол. Включён по умолчанию; выключить — Настройки → «Значок «Записать»»
 *  (компонент выключается: значок пропадает из списка виджетов). Добавить на экран — requestPinAppWidget (Android 8+). */
public class CaptureWidget extends AppWidgetProvider {
    @Override public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        for (int id : ids) m.updateAppWidget(id, views(c));
    }

    static RemoteViews views(Context c) {
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_capture);
        Intent i = new Intent(c, MainActivity.class).setAction("pro.dewiar.CAPTURE")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        v.setOnClickPendingIntent(R.id.w_root, PendingIntent.getActivity(c, 7301, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        return v;
    }

    static ComponentName cn(Context c) { return new ComponentName(c, CaptureWidget.class); }

    /** -> {on: значок доступен, placed: сколько на экранах, pin: можно добавить кнопкой из приложения} */
    static JSONObject state(Context c) {
        JSONObject o = new JSONObject();
        try {
            int st = c.getPackageManager().getComponentEnabledSetting(cn(c));
            int placed = AppWidgetManager.getInstance(c).getAppWidgetIds(cn(c)).length;
            o.put("on", st != PackageManager.COMPONENT_ENABLED_STATE_DISABLED).put("placed", placed).put("pin", pinSupported(c));
        } catch (Exception ignored) { }
        return o;
    }

    static void set(Context c, boolean on) {
        c.getPackageManager().setComponentEnabledSetting(cn(c), on ? PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                : PackageManager.COMPONENT_ENABLED_STATE_DISABLED, PackageManager.DONT_KILL_APP);
    }

    // requestPinAppWidget — Android 8 (API 26); собираем против 23, поэтому отражением
    static boolean pinSupported(Context c) {
        if (android.os.Build.VERSION.SDK_INT < 26) return false;
        try { return (Boolean) AppWidgetManager.class.getMethod("isRequestPinAppWidgetSupported").invoke(AppWidgetManager.getInstance(c)); }
        catch (Throwable e) { return false; }
    }

    static boolean pin(Context c) {
        if (!pinSupported(c)) return false;
        try {
            return (Boolean) AppWidgetManager.class.getMethod("requestPinAppWidget", ComponentName.class, android.os.Bundle.class, PendingIntent.class)
                    .invoke(AppWidgetManager.getInstance(c), cn(c), null, null);
        } catch (Throwable e) { return false; }
    }
}
