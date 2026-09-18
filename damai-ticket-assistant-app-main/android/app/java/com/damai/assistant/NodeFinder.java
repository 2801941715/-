package com.damai.assistant;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;
import android.view.accessibility.AccessibilityNodeInfo;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * 无障碍节点查询与手势引擎。
 *
 * 等价于 Python 侧依赖 Appium 完成的：
 *   - find_element / find_elements（多种定位策略）
 *   - WebDriverWait + presence_of_element_located（轮询等待）
 *   - driver.execute_script("mobile: clickGesture", ...)（原生坐标点击）
 *   - mobile: scrollGesture（原生滚动）
 *
 * 全部通过 AccessibilityService 的节点树与手势 API 在设备本地实现，
 * 无需 Appium server，也无需 USB 连接。
 */
public class NodeFinder {

    private static final String TAG = "DamaiNodeFinder";

    /** 定位策略（对应 Appium 的 By.*）。 */
    public enum By {
        /** 精确文本：new UiSelector().text("x") */
        TEXT,
        /** 包含文本：new UiSelector().textContains("x") */
        TEXT_CONTAINS,
        /** 资源 id：等价 By.ID（支持 "cn.damai:id/xxx" 或 "xxx"） */
        ID,
        /** 类名：等价 By.CLASS_NAME / XPath @class */
        CLASS_NAME,
        /** 文本正则：等价 textMatches(".*x.*") */
        TEXT_MATCHES
    }

    /** 一条定位条件，等价于 (by, value) 二元组。 */
    public static final class Selector {
        public final By by;
        public final String value;

        public Selector(By by, String value) {
            this.by = by;
            this.value = value;
        }

        public static Selector text(String v) {
            return new Selector(By.TEXT, v);
        }

        public static Selector textContains(String v) {
            return new Selector(By.TEXT_CONTAINS, v);
        }

        public static Selector id(String v) {
            return new Selector(By.ID, v);
        }

        public static Selector className(String v) {
            return new Selector(By.CLASS_NAME, v);
        }

        public static Selector textMatches(String v) {
            return new Selector(By.TEXT_MATCHES, v);
        }

        @Override
        public String toString() {
            return by + ":" + value;
        }
    }

    private final AccessibilityService service;

    /**
     * 手势回调专用线程。
     *
     * dispatchGesture 会「取消」尚未完成的上一个手势；若连续快速点击（例如
     * 批量勾选观演人），后一次派发会打断前一次，导致只有最后一次点击生效。
     * 因此每次手势都必须等待完成后再派发下一次。
     *
     * 回调若投递到主线程，而调用方（抢票工作线程）阻塞等待，会造成死锁；
     * 这里统一把回调投递到独立的 HandlerThread，从而可在任意线程安全等待。
     */
    private static HandlerThread gestureThread;
    private static Handler gestureHandler;

    public NodeFinder(AccessibilityService service) {
        this.service = service;
    }

    /**
     * 注入通道。
     *
     * 实测：大麦 App 会过滤掉来自无障碍服务的注入手势（dispatchGesture 返回成功、
     * 回调 onCompleted，但应用不响应；同一坐标用 adb input tap 有效）。
     * 因此把「执行点击」抽象成可切换通道，便于在受限环境下改用具备 ADB 权限的注入方式。
     */
    public interface Injector {
        /** 返回是否已成功注入一次点击。 */
        boolean tap(int x, int y);

        String name();
    }

    private Injector injector = new A11yInjector();

    /** 无障碍手势注入（默认；对普通应用有效）。 */
    private final class A11yInjector implements Injector {
        @Override
        public boolean tap(int x, int y) {
            return clickAt(x, y, 50L);
        }

        @Override
        public String name() {
            return "a11y";
        }
    }

    public void setInjector(Injector injector) {
        if (injector != null) {
            this.injector = injector;
        }
    }

    public Injector getInjector() {
        return injector;
    }

    public String injectorName() {
        return injector == null ? "(none)" : injector.name();
    }

    /**
     * 用无障碍 ACTION_CLICK 直接点击节点（不派发手势）。
     *
     * 实测（大麦 9.0.28）适用边界：
     *   - 标准 Android 控件（底部 tab 容器、CheckBox 等）→ **有效**
     *   - 自定义绘制按钮（购买入口 / 确定）→ 无 clickable 节点，**无法使用**
     * 因此它作为「手势注入被拦截」时的补充通道。
     *
     * @param useAncestor 节点自身不可点击时，是否向上找可点击祖先
     */
    public boolean actionClick(AccessibilityNodeInfo node, boolean useAncestor) {
        if (node == null) {
            return false;
        }
        AccessibilityNodeInfo target = node;
        if (!target.isClickable()) {
            if (!useAncestor) {
                return false;
            }
            target = clickableAncestor(node);
            if (target == null) {
                return false;
            }
        }
        try {
            return target.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        } catch (Exception e) {
            Log.w(TAG, "actionClick failed: " + e);
            return false;
        }
    }

    /** 判断当前无障碍服务是否具备派发手势的能力。 */
    public static boolean canPerformGestures(AccessibilityService service) {
        if (service == null || Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        try {
            AccessibilityServiceInfo info = service.getServiceInfo();
            if (info == null) {
                return false;
            }
            int caps = info.getCapabilities();
            return (caps & AccessibilityServiceInfo.CAPABILITY_CAN_PERFORM_GESTURES) != 0;
        } catch (Exception e) {
            Log.w(TAG, "canPerformGestures failed: " + e);
            return false;
        }
    }

    private static synchronized Handler gestureHandler() {
        if (gestureHandler == null) {
            gestureThread = new HandlerThread("damai-gesture");
            gestureThread.start();
            gestureHandler = new Handler(gestureThread.getLooper());
        }
        return gestureHandler;
    }

    // ------------------------------------------------------------------
    // 节点查询
    // ------------------------------------------------------------------

    /** 根节点不可用时返回 null（等价 Appium 连接断开）。 */
    public AccessibilityNodeInfo root() {
        try {
            return service.getRootInActiveWindow();
        } catch (Exception e) {
            Log.w(TAG, "getRootInActiveWindow failed: " + e);
            return null;
        }
    }

    public boolean isReady() {
        return root() != null;
    }

    private boolean matches(AccessibilityNodeInfo node, Selector sel) {
        if (node == null) {
            return false;
        }
        String text = node.getText() == null ? "" : node.getText().toString();
        String desc = node.getContentDescription() == null ? "" : node.getContentDescription().toString();
        String viewId = node.getViewIdResourceName();

        switch (sel.by) {
            case TEXT:
                return text.equals(sel.value) || desc.equals(sel.value);
            case TEXT_CONTAINS:
                return text.contains(sel.value) || desc.contains(sel.value);
            case TEXT_MATCHES:
                return text.matches(sel.value) || desc.matches(sel.value);
            case ID: {
                if (viewId == null) {
                    return false;
                }
                String want = sel.value;
                // 支持 "包名:id/name" 与 "name" 两种写法
                if (want.contains(":id/")) {
                    return viewId.equals(want);
                }
                return viewId.equals(want) || viewId.endsWith(":id/" + want);
            }
            case CLASS_NAME: {
                CharSequence cls = node.getClassName();
                return cls != null && cls.toString().equals(sel.value);
            }
            default:
                return false;
        }
    }

    /** 收集整棵树中所有匹配节点（等价 find_elements）。 */
    public List<AccessibilityNodeInfo> findElements(Selector sel) {
        List<AccessibilityNodeInfo> out = new ArrayList<AccessibilityNodeInfo>();
        AccessibilityNodeInfo r = root();
        if (r == null) {
            return out;
        }
        collect(r, sel, out, 0);
        return out;
    }

    private void collect(AccessibilityNodeInfo node, Selector sel, List<AccessibilityNodeInfo> out, int depth) {
        if (node == null || depth > 60 || out.size() > 400) {
            return;
        }
        if (matches(node, sel)) {
            out.add(node);
        }
        int n = node.getChildCount();
        for (int i = 0; i < n; i++) {
            AccessibilityNodeInfo child;
            try {
                child = node.getChild(i);
            } catch (Exception e) {
                continue;
            }
            collect(child, sel, out, depth + 1);
        }
    }

    /** 按优先级依次尝试多个定位条件，返回首个命中的节点（等价 find_element + fallback）。 */
    public AccessibilityNodeInfo findFirst(Selector... selectors) {
        for (Selector sel : selectors) {
            List<AccessibilityNodeInfo> list = findElements(sel);
            if (!list.isEmpty()) {
                return list.get(0);
            }
        }
        return null;
    }

    /** 与 findFirst 相同，但会在超时时间内轮询（等价 WebDriverWait）。 */
    public AccessibilityNodeInfo waitForAny(long timeoutMs, long pollMs, Selector... selectors) {
        long deadline = System.currentTimeMillis() + Math.max(0, timeoutMs);
        do {
            AccessibilityNodeInfo hit = findFirst(selectors);
            if (hit != null) {
                return hit;
            }
            if (System.currentTimeMillis() >= deadline) {
                break;
            }
            sleep(pollMs);
        } while (true);
        return null;
    }

    /**
     * 等待某个选择器从界面上消失（等价「弹窗已关闭 / 页面已跳转」）。
     *
     * @return true 表示在超时前确认消失
     */
    public boolean waitUntilGone(long timeoutMs, long pollMs, Selector selector) {
        long deadline = System.currentTimeMillis() + Math.max(0, timeoutMs);
        do {
            if (findFirst(selector) == null) {
                return true;
            }
            if (System.currentTimeMillis() >= deadline) {
                break;
            }
            sleep(pollMs);
        } while (true);
        return findFirst(selector) == null;
    }

    /**
     * 等待界面「稳定」下来：连续一段时间内节点总数不再变化。
     *
     * 用于点击「立即购票」之后——大麦会先弹窗、再切换页面，
     * 必须等页面真正就绪再继续，否则会在旧页面上找不到目标元素。
     *
     * @param quiesceMs 连续稳定多久视为就绪
     */
    public void waitForStable(long timeoutMs, long quiesceMs) {
        long deadline = System.currentTimeMillis() + Math.max(0, timeoutMs);
        int lastCount = -1;
        long stableSince = 0L;
        while (System.currentTimeMillis() < deadline) {
            int count = countNodes(root(), 0, 6000);
            long now = System.currentTimeMillis();
            if (count == lastCount) {
                if (stableSince == 0L) {
                    stableSince = now;
                } else if (now - stableSince >= quiesceMs) {
                    return;
                }
            } else {
                lastCount = count;
                stableSince = now;
            }
            sleep(120L);
        }
    }

    private int countNodes(AccessibilityNodeInfo node, int depth, int limit) {
        if (node == null || depth > 60) {
            return 0;
        }
        int n = 1;
        int childCount;
        try {
            childCount = node.getChildCount();
        } catch (Exception ignored) {
            return n;
        }
        for (int i = 0; i < childCount && n < limit; i++) {
            AccessibilityNodeInfo child = null;
            try {
                child = node.getChild(i);
            } catch (Exception ignored) {
                continue;
            }
            n += countNodes(child, depth + 1, limit);
        }
        return n;
    }

    /** 判断整棵树中是否存在任意一个含指定文本（或描述）的节点。 */
    public boolean hasText(String keyword) {
        if (keyword == null || keyword.isEmpty()) {
            return false;
        }
        return !findElements(Selector.textContains(keyword)).isEmpty();
    }

    /**
     * 异步点击（不等待手势完成）。
     *
     * 用于「点击后立刻会跳页/弹窗」的场景：此时等待完成没有意义，
     * 反而会因页面切换而收到 onCancelled，误判为点击失败。
     */
    /** 通过当前注入通道执行一次坐标点击。 */
    public boolean tapVia(int x, int y) {
        try {
            return injector != null && injector.tap(x, y);
        } catch (Exception e) {
            Log.w(TAG, "tapVia failed: " + e);
            return false;
        }
    }

    public boolean clickAtAsync(int x, int y, long durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        Path path = new Path();
        path.moveTo(Math.max(0, x), Math.max(0, y));
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, Math.max(1L, durationMs));
        GestureDescription gesture = new GestureDescription.Builder().addStroke(stroke).build();
        try {
            return service.dispatchGesture(gesture, null, gestureHandler());
        } catch (Exception e) {
            Log.w(TAG, "dispatchGesture async failed: " + e);
            return false;
        }
    }

    // ------------------------------------------------------------------
    // 节点信息
    // ------------------------------------------------------------------

    public static Rect boundsOf(AccessibilityNodeInfo node) {
        Rect r = new Rect();
        if (node != null) {
            node.getBoundsInScreen(r);
        }
        return r;
    }

    public static boolean isChecked(AccessibilityNodeInfo node) {
        if (node == null) {
            return false;
        }
        if (node.isCheckable()) {
            return node.isChecked();
        }
        // 部分页面把勾选状态放在子节点上
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null && child.isCheckable()) {
                return child.isChecked();
            }
        }
        return false;
    }

    /** 在节点子树中按 id 查找（等价 element.find_element(By.ID, ...)）。 */
    public static AccessibilityNodeInfo findInSubtree(AccessibilityNodeInfo root, Selector sel) {
        if (root == null) {
            return null;
        }
        List<AccessibilityNodeInfo> out = new ArrayList<AccessibilityNodeInfo>();
        // 复用匹配逻辑（不依赖 service 实例）
        collectStatic(root, sel, out, 0);
        return out.isEmpty() ? null : out.get(0);
    }

    private static void collectStatic(AccessibilityNodeInfo node, Selector sel, List<AccessibilityNodeInfo> out, int depth) {
        if (node == null || depth > 40 || out.size() > 100) {
            return;
        }
        if (matchesStatic(node, sel)) {
            out.add(node);
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            collectStatic(child, sel, out, depth + 1);
        }
    }

    private static boolean matchesStatic(AccessibilityNodeInfo node, Selector sel) {
        if (node == null) {
            return false;
        }
        String text = node.getText() == null ? "" : node.getText().toString();
        String viewId = node.getViewIdResourceName();
        switch (sel.by) {
            case TEXT:
                return text.equals(sel.value);
            case TEXT_CONTAINS:
                return text.contains(sel.value);
            case TEXT_MATCHES:
                return text.matches(sel.value);
            case ID: {
                if (viewId == null) {
                    return false;
                }
                String want = sel.value;
                if (want.contains(":id/")) {
                    return viewId.equals(want);
                }
                return viewId.equals(want) || viewId.endsWith(":id/" + want);
            }
            case CLASS_NAME: {
                CharSequence cls = node.getClassName();
                return cls != null && cls.toString().equals(sel.value);
            }
            default:
                return false;
        }
    }

    /** 向上查找最近的可点击祖先（等价 XPath ancestor::*[@clickable="true"][1]）。 */
    public static AccessibilityNodeInfo clickableAncestor(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo cur = node;
        int guard = 0;
        while (cur != null && guard++ < 20) {
            if (cur.isClickable()) {
                return cur;
            }
            cur = cur.getParent();
        }
        return null;
    }

    // ------------------------------------------------------------------
    // 手势
    // ------------------------------------------------------------------

    /**
     * 原生坐标点击（等价 mobile: clickGesture x/y/duration）。
     *
     * 同步等待手势完成后再返回，避免连续点击时后一次派发取消前一次。
     */
    public boolean clickAt(int x, int y, long durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        Path path = new Path();
        path.moveTo(Math.max(0, x), Math.max(0, y));
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, Math.max(1L, durationMs));
        GestureDescription gesture = new GestureDescription.Builder().addStroke(stroke).build();
        return dispatchAndWait(gesture, Math.max(1L, durationMs));
    }

    /**
     * 派发手势并等待其结束（完成或取消）。
     *
     * @param extraTimeoutMs 除手势时长外的额外等待余量
     * @return true 表示手势正常完成（未被取消、未超时）
     */
    /** 最近一次手势的结果码：0=完成 1=取消 2=超时 3=未派发。用于诊断。 */
    public static volatile int lastGestureResult = -1;

    /** 判决性诊断：派发一次点击并报告回调结果。 */
    public int probeClick(int x, int y, long durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return 3;
        }
        Path path = new Path();
        path.moveTo(Math.max(0, x), Math.max(0, y));
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, Math.max(1L, durationMs));
        GestureDescription gesture = new GestureDescription.Builder().addStroke(stroke).build();

        final CountDownLatch latch = new CountDownLatch(1);
        final int[] outcome = new int[]{2};
        AccessibilityService.GestureResultCallback cb =
                new AccessibilityService.GestureResultCallback() {
                    @Override
                    public void onCompleted(GestureDescription d) {
                        outcome[0] = 0;
                        latch.countDown();
                    }

                    @Override
                    public void onCancelled(GestureDescription d) {
                        outcome[0] = 1;
                        latch.countDown();
                    }
                };
        boolean dispatched;
        try {
            dispatched = service.dispatchGesture(gesture, cb, gestureHandler());
        } catch (Exception e) {
            Log.w(TAG, "probeClick dispatch failed: " + e);
            return 3;
        }
        if (!dispatched) {
            return 3;
        }
        try {
            latch.await(durationMs + 3000L, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        lastGestureResult = outcome[0];
        return outcome[0];
    }

    private boolean dispatchAndWait(GestureDescription gesture, long extraTimeoutMs) {
        final CountDownLatch latch = new CountDownLatch(1);
        final boolean[] completed = new boolean[]{false};
        // 注意：GestureResultCallback 是 AccessibilityService 的嵌套类
        AccessibilityService.GestureResultCallback callback =
                new AccessibilityService.GestureResultCallback() {
                    @Override
                    public void onCompleted(GestureDescription description) {
                        completed[0] = true;
                        latch.countDown();
                    }

                    @Override
                    public void onCancelled(GestureDescription description) {
                        completed[0] = false;
                        latch.countDown();
                    }
                };
        boolean dispatched;
        try {
            dispatched = service.dispatchGesture(gesture, callback, gestureHandler());
        } catch (Exception e) {
            Log.w(TAG, "dispatchGesture failed: " + e);
            return false;
        }
        if (!dispatched) {
            Log.w(TAG, "dispatchGesture returned false (gesture not accepted)");
            return false;
        }
        try {
            if (!latch.await(extraTimeoutMs + 3000L, TimeUnit.MILLISECONDS)) {
                Log.w(TAG, "gesture wait timed out");
                return false;
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
        return completed[0];
    }

    /** 点击节点中心；节点不可点击时尝试向上寻找可点击祖先。 */
    public boolean clickNode(AccessibilityNodeInfo node) {
        if (node == null) {
            return false;
        }
        Rect r = boundsOf(node);
        if (r.width() > 0 && r.height() > 0) {
            if (tapVia(r.centerX(), r.centerY())) {
                return true;
            }
        }
        // 手势不可用/被拦截时，退回无障碍 ACTION_CLICK（对标准控件有效）
        return actionClick(node, true);
    }

    /** 原生滚动（等价 mobile: scrollGesture，direction=down）。 */
    public boolean scrollDown(Rect area, float percent) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N || area == null || area.width() <= 0) {
            return false;
        }
        int x = area.centerX();
        int startY = area.top + (int) (area.height() * 0.80f);
        int endY = area.top + (int) (area.height() * (0.80f - Math.max(0.05f, Math.min(0.9f, percent))));
        Path path = new Path();
        path.moveTo(x, startY);
        path.lineTo(x, Math.max(area.top + 1, endY));
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, 300L);
        GestureDescription gesture = new GestureDescription.Builder().addStroke(stroke).build();
        return dispatchAndWait(gesture, 300L);
    }

    public static void sleep(long ms) {
        if (ms <= 0) {
            return;
        }
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /** 便于日志输出。 */
    public static String describe(AccessibilityNodeInfo node) {
        if (node == null) {
            return "<null>";
        }
        CharSequence text = node.getText();
        Rect r = boundsOf(node);
        return String.format(Locale.US, "%s[%s](%d,%d,%d,%d)",
                node.getClassName(), text == null ? "" : text.toString(),
                r.left, r.top, r.right, r.bottom);
    }
}
