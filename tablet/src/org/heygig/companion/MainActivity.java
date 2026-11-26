package org.heygig.companion;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import java.io.ByteArrayInputStream;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final String ORIGIN = "http://127.0.0.1:18765";
    private static final String HOME = ORIGIN + "/?companion";
    private static final int MICROPHONE_PERMISSION = 101;
    private PermissionRequest microphoneRequest;

    private static boolean isCompanionOrigin(Uri origin) {
        return "http".equals(origin.getScheme())
            && "127.0.0.1".equals(origin.getHost())
            && origin.getPort() == 18765;
    }

    private static boolean isExternalHandoff(Uri uri) {
        if (!"https".equals(uri.getScheme()) || uri.getPort() != -1 || uri.getUserInfo() != null) return false;
        String host = uri.getHost();
        String path = uri.getPath();
        if (path == null) return false;
        return ("wa.me".equals(host) && path.matches("/[1-9][0-9]{7,14}"))
            || ("www.google.com".equals(host) && "/maps/dir/".equals(path))
            || ("drive.google.com".equals(host) && path.startsWith("/file/d/"));
    }

    private void handleMicrophoneRequest(PermissionRequest request) {
        String[] resources = request.getResources();
        if (!isCompanionOrigin(request.getOrigin()) || resources.length != 1
                || !PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[0])
                || microphoneRequest != null) {
            request.deny();
            return;
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            return;
        }
        microphoneRequest = request;
        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MICROPHONE_PERMISSION);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != MICROPHONE_PERMISSION || microphoneRequest == null) return;

        PermissionRequest request = microphoneRequest;
        microphoneRequest = null;
        if (grantResults.length == 1 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
        } else {
            request.deny();
        }
    }

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        WebView view = new WebView(this);
        view.getSettings().setJavaScriptEnabled(true);
        view.getSettings().setAllowFileAccess(false);
        view.getSettings().setAllowContentAccess(false);
        view.getSettings().setMediaPlaybackRequiresUserGesture(false);
        view.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                handleMicrophoneRequest(request);
            }

            @Override
            public void onPermissionRequestCanceled(PermissionRequest request) {
                if (request == microphoneRequest) microphoneRequest = null;
            }
        });
        view.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView web, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (isCompanionOrigin(uri)) return false;
                if (request.isForMainFrame() && request.hasGesture() && isExternalHandoff(uri)) {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE));
                    } catch (ActivityNotFoundException exception) {
                        Toast.makeText(MainActivity.this, "No app can open this link.", Toast.LENGTH_LONG).show();
                    }
                }
                return true;
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
