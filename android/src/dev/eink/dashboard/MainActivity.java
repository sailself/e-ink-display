package dev.eink.dashboard;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ActivityInfo;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.text.DateFormat;
import java.util.Date;

/**
 * Fullscreen kiosk WebView for the e-ink dashboard.
 *
 * - keeps the screen on, hides status/navigation bars
 * - cycles through a list of URLs (USB/localhost first, then Wi-Fi) and retries forever
 * - exposes battery info to the page as window.Device
 *
 * Override the URL list once with:  adb shell am start -n dev.eink.dashboard/.MainActivity --es urls "http://host:8787/"
 */
public class MainActivity extends Activity {
    public static final String EXTRA_URLS = "urls";
    public static final String EXTRA_ORIENTATION = "orientation";
    private static final String PREFS = "dash";
    private static final String PREF_GOOD_INDEX = "good_index";
    private static final String PREF_ORIENTATION = "orientation";
    private static final long RETRY_MS = 20_000;
    private static final long WATCHDOG_MS = 10 * 60_000;
    private static final long STALE_MS = 45 * 60_000;

    private WebView web;
    private String[] urls;
    private String orientation = "portrait";
    private int urlIndex = 0;
    private long lastGoodLoad = 0;
    private boolean currentLoadFailed = false;
    private final Handler handler = new Handler(Looper.getMainLooper());

    private final Runnable retry = new Runnable() {
        @Override public void run() { load(); }
    };
    private final Runnable watchdog = new Runnable() {
        @Override public void run() {
            if (System.currentTimeMillis() - lastGoodLoad > STALE_MS) load();
            handler.postDelayed(this, WATCHDOG_MS);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Window w = getWindow();
        w.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        setShowWhenLocked(true);
        setTurnScreenOn(true);
        orientation = getSharedPreferences(PREFS, MODE_PRIVATE).getString(PREF_ORIENTATION, "portrait");
        applyOrientation(orientation);

        web = new WebView(this);
        web.setBackgroundColor(Color.WHITE);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.addJavascriptInterface(new Bridge(), "Device");
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageStarted(WebView v, String url, Bitmap favicon) { currentLoadFailed = false; }

            @Override public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) failed(String.valueOf(err.getDescription()));
            }

            @Override public void onReceivedHttpError(WebView v, WebResourceRequest req, WebResourceResponse resp) {
                if (req.isForMainFrame()) failed("HTTP " + resp.getStatusCode());
            }

            @Override public void onPageFinished(WebView v, String url) {
                if (!currentLoadFailed && !url.startsWith("data:")) {
                    lastGoodLoad = System.currentTimeMillis();
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit().putInt(PREF_GOOD_INDEX, urlIndex % urls.length).apply();
                }
            }
        });
        setContentView(web);
        hideSystemUI();  // needs the decor view, so only after setContentView

        urls = resolveUrls(getIntent());
        urlIndex = getSharedPreferences(PREFS, MODE_PRIVATE).getInt(PREF_GOOD_INDEX, 0) % urls.length;  // start with what last worked
        applyIntentOrientation(getIntent());
        load();
        handler.postDelayed(watchdog, WATCHDOG_MS);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (intent == null) return;
        applyIntentOrientation(intent);
        if (intent.hasExtra(EXTRA_URLS)) {
            urls = resolveUrls(intent);
            urlIndex = 0;
            load();
        }
    }

    /** `am start ... --es orientation landscape` overrides the config-driven value until the page sends a new one. */
    private void applyIntentOrientation(Intent intent) {
        String o = intent.getStringExtra(EXTRA_ORIENTATION);
        if (o != null && !o.trim().isEmpty()) setOrientationMode(o.trim());
    }

    private void setOrientationMode(String mode) {
        if (mode.equals(orientation)) return;
        orientation = mode;
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(PREF_ORIENTATION, mode).apply();
        applyOrientation(mode);
    }

    private void applyOrientation(String mode) {
        int o;
        switch (mode) {
            case "landscape": o = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE; break;
            case "reverse-landscape": o = ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE; break;
            case "reverse-portrait": o = ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT; break;
            case "sensor-landscape": o = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE; break;
            case "sensor-portrait": o = ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT; break;
            case "auto": case "sensor": o = ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR; break;
            default: o = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT;
        }
        setRequestedOrientation(o);
    }

    private String[] resolveUrls(Intent intent) {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        String list = intent != null ? intent.getStringExtra(EXTRA_URLS) : null;
        if (list != null && !list.trim().isEmpty()) {
            p.edit().putString(EXTRA_URLS, list.trim()).apply();
        } else {
            list = p.getString(EXTRA_URLS, getString(R.string.default_urls));
        }
        return list.split("\\s*,\\s*");
    }

    private void load() {
        handler.removeCallbacks(retry);
        String url = urls[urlIndex % urls.length];
        web.loadUrl(url);
    }

    private void failed(String why) {
        currentLoadFailed = true;
        String tried = urls[urlIndex % urls.length];
        urlIndex = (urlIndex + 1) % urls.length;
        String now = DateFormat.getTimeInstance(DateFormat.SHORT).format(new Date());
        String html = "<!doctype html><meta name=viewport content='width=device-width'>"
                + "<body style='margin:0;background:#fff;color:#000;font-family:sans-serif;padding:8vw'>"
                + "<div style='font-size:9vw;font-weight:900;margin-top:30vh'>Dashboard offline</div>"
                + "<div style='font-size:4vw;margin-top:4vw'>" + escape(why) + "</div>"
                + "<div style='font-size:3.4vw;margin-top:2vw;color:#555'>Tried " + escape(tried) + " at " + now + "</div>"
                + "<div style='font-size:3.4vw;margin-top:1vw;color:#555'>Retrying every " + (RETRY_MS / 1000) + "s. Is the server running on the PC?</div>"
                + "</body>";
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
        handler.postDelayed(retry, RETRY_MS);
    }

    private static String escape(String s) {
        return s == null ? "" : s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }

    private void hideSystemUI() {
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            w.setDecorFitsSystemWindows(false);
            WindowInsetsController c = w.getInsetsController();
            if (c != null) {
                c.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            w.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemUI();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemUI();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (web != null) web.destroy();
        super.onDestroy();
    }

    /** Exposed to the page as window.Device. */
    private class Bridge {
        private BatteryManager bm() { return (BatteryManager) getSystemService(BATTERY_SERVICE); }

        @JavascriptInterface public int battery() { return bm().getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY); }
        @JavascriptInterface public boolean charging() { return bm().isCharging(); }
        @JavascriptInterface public String model() { return Build.MANUFACTURER + " " + Build.MODEL; }

        /** config.json's dashboard.orientation, relayed by the page after every successful poll. */
        @JavascriptInterface public void setOrientation(final String mode) {
            if (mode == null) return;
            handler.post(new Runnable() {
                @Override public void run() { setOrientationMode(mode.trim()); }
            });
        }

        /** The page lost its server (its fetches keep failing): move on to the next URL in the list. */
        @JavascriptInterface public void switchUrl() {
            handler.post(new Runnable() {
                @Override public void run() { failed("page lost its server"); }
            });
        }
    }
}
