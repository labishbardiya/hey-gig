package org.heygig.companion;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.ByteArrayInputStream;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final String ORIGIN = "http://127.0.0.1:18765";
    private static final String HOME = ORIGIN + "/?companion";

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        WebView view = new WebView(this);
        view.getSettings().setJavaScriptEnabled(true);
        view.getSettings().setAllowFileAccess(false);
        view.getSettings().setAllowContentAccess(false);
        view.setWebChromeClient(new WebChromeClient());
        view.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView web, WebResourceRequest request) {
                return !request.getUrl().toString().startsWith(ORIGIN + "/");
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView web, WebResourceRequest request) {
                if (request.getUrl().toString().startsWith(ORIGIN + "/")) return null;
                return new WebResourceResponse("text/plain", "UTF-8", new ByteArrayInputStream(new byte[0]));
            }

            @Override
            public void onPageFinished(WebView web, String url) {
                String token = getIntent().getStringExtra("session_token");
                if (HOME.equals(url) && token != null) {
                    web.evaluateJavascript("document.getElementById('token').value=" +
                        JSONObject.quote(token) + ";document.getElementById('connect').click()", null);
                    getIntent().removeExtra("session_token");
                }
            }
        });
        setContentView(view);
        view.loadUrl(HOME);
    }
}
