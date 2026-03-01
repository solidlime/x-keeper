package com.solidlime.xkeeper_client

import android.widget.Toast
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.solidlime.xkeeper_client/toast")
            .setMethodCallHandler { call, result ->
                if (call.method == "show") {
                    val message = call.argument<String>("message") ?: ""
                    Toast.makeText(applicationContext, message, Toast.LENGTH_SHORT).show()
                    result.success(null)
                } else {
                    result.notImplemented()
                }
            }
    }
}
