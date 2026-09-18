package com.damai.assistant;

import android.accessibilityservice.AccessibilityService;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;

/**
 * 大麦抢票助手的无障碍服务。
 *
 * 这是手机端自动化的执行引擎：开启后即可在设备本地操控大麦 App，
 * 并通过 {@link RemoteBridge} 在 127.0.0.1 的调试端口上暴露控制接口，
 * 供 Windows 侧通过 `adb forward` 远程调试。
 */
public class DamaiAutomationService extends AccessibilityService {

    private static final String TAG = "DamaiA11yService";

    private static volatile DamaiAutomationService instance;
    private static final Object DUMP_LOCK = new Object();
    private static String lastDump = "";

    private RemoteBridge bridge;

    public static DamaiAutomationService getInstance() {
        return instance;
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        Log.i(TAG, "accessibility service connected");
        try {
            bridge = new RemoteBridge(this);
            bridge.start();
        } catch (Exception e) {
            Log.e(TAG, "failed to start remote bridge", e);
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // 抢票流程为主动轮询式，这里只保留一份节点快照供远程调试查看
        try {
            synchronized (DUMP_LOCK) {
                lastDump = NodeDumper.dump(getRootInActiveWindow());
            }
        } catch (Exception ignored) {
            // 忽略：事件回调内的异常不应影响系统
        }
    }

    @Override
    public void onInterrupt() {
        Log.i(TAG, "accessibility service interrupted");
    }

    @Override
    public boolean onUnbind(android.content.Intent intent) {
        Log.i(TAG, "accessibility service unbound");
        if (bridge != null) {
            bridge.stop();
            bridge = null;
        }
        if (instance == this) {
            instance = null;
        }
        return super.onUnbind(intent);
    }

    /** 供远程调试读取当前页面层级快照。 */
    public static String getLastDump() {
        synchronized (DUMP_LOCK) {
            return lastDump;
        }
    }
}
