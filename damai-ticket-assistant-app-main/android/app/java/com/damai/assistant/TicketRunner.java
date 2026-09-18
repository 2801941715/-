package com.damai.assistant;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * 抢票流程执行器（在手机本地运行）。
 *
 * 与 Python 侧 damai_appium.runner.DamaiAppTicketRunner 的流程一一对应，
 * 但把 Appium 驱动替换为设备内的 AccessibilityService：
 *
 *   Python (Appium)                     →  本实现 (本地无障碍)
 *   ------------------------------------  ------------------------------------
 *   webdriver.Remote(endpoint, caps)     →  NodeFinder(service)
 *   WebDriverWait(...).until(presence)   →  NodeFinder.waitForAny(...)
 *   mobile: clickGesture {x,y,duration}  →  NodeFinder.clickAt(...)
 *   mobile: scrollGesture                →  NodeFinder.scrollDown(...)
 */
public class TicketRunner {

    public interface Logger {
        void log(String level, String message, JSONObject context);
    }

    public interface StopSignal {
        boolean shouldStop();
    }

    private final AccessibilityService service;
    private final Config config;
    private final Logger logger;
    private final StopSignal stopSignal;
    private final NodeFinder finder;

    private String phase = Phase.INIT;
    private final List<String> phaseHistory = new ArrayList<String>();
    private String failureCode;
    private String failureReason;

    public TicketRunner(AccessibilityService service, Config config, Logger logger, StopSignal stopSignal) {
        this.service = service;
        this.config = config;
        this.logger = logger;
        this.stopSignal = stopSignal;
        this.finder = new NodeFinder(service);
        this.phaseHistory.add(Phase.INIT);
    }

    public String getPhase() {
        return phase;
    }

    public List<String> getPhaseHistory() {
        return new ArrayList<String>(phaseHistory);
    }

    public String getFailureCode() {
        return failureCode;
    }

    public String getFailureReason() {
        return failureReason;
    }

    // ------------------------------------------------------------------
    // 状态
    // ------------------------------------------------------------------

    private void transitionTo(String next) {
        if (next == null || next.equals(phase)) {
            return;
        }
        phase = next;
        phaseHistory.add(next);
    }

    private void markFailure() {
        if (!Phase.FAILED.equals(phase)) {
            transitionTo(Phase.FAILED);
        }
    }

    private void markStopped() {
        if (!Phase.STOPPED.equals(phase)) {
            transitionTo(Phase.STOPPED);
        }
    }

    private void log(String level, String message) {
        log(level, message, null);
    }

    private void log(String level, String message, JSONObject context) {
        if (logger != null) {
            JSONObject ctx = context == null ? new JSONObject() : context;
            try {
                if (!ctx.has("phase")) {
                    ctx.put("phase", phase);
                }
            } catch (Exception ignored) {
                // 忽略：上下文写入失败不影响主流程
            }
            logger.log(level, message, ctx);
        }
    }

    private void ensureNotStopped() throws StoppedException {
        if (shouldStop()) {
            throw new StoppedException("用户已停止流程");
        }
    }

    private boolean shouldStop() {
        try {
            return stopSignal != null && stopSignal.shouldStop();
        } catch (Exception e) {
            return false;
        }
    }

    /** 用户主动停止（等价 TicketRunnerStopped）。 */
    public static class StoppedException extends Exception {
        public StoppedException(String msg) {
            super(msg);
        }
    }

    /** 流程错误（等价 TicketRunnerError）。 */
    public static class FlowException extends Exception {
        public FlowException(String msg) {
            super(msg);
        }
    }

    private long waitMs() {
        return (long) Math.max(config.waitTimeout, 0.2d) * 1000L;
    }

    // ------------------------------------------------------------------
    // 公开入口
    // ------------------------------------------------------------------

    /** 执行一次完整抢票流程；失败抛出异常，由调用方决定是否重试。 */
    public void runOnce() throws FlowException, StoppedException {
        transitionTo(Phase.CONNECTING);
        ensureNotStopped();
        if (!finder.isReady()) {
            throw new FlowException("无障碍服务尚未就绪（请确认已开启本应用的无障碍权限）");
        }
        log(LogLevel.STEP, "无障碍服务已就绪");

        transitionTo(Phase.APPLYING_SETTINGS);
        performFlow();
    }

    private void performFlow() throws FlowException, StoppedException {
        // 进入流程前，先清除可能残留的弹窗（票务须知 / 实名制提示等）
        dismissBlockingDialogs();

        // 1) 选择城市
        if (notBlank(config.city)) {
            transitionTo(Phase.SELECTING_CITY);
            log(LogLevel.STEP, "选择城市: " + config.city);
            if (!selectCity(config.city)) {
                log(LogLevel.WARNING, "未找到城市 " + config.city);
            }
        }

        // 2) 点击购买/预约按钮（含“努力刷新”兜底）
        ensureNotStopped();
        transitionTo(Phase.TAPPING_PURCHASE);
        log(LogLevel.STEP, "尝试点击预约/购买按钮");
        if (!tapPurchaseButton()) {
            log(LogLevel.INFO, "未找到购买入口，检测“努力刷新”按钮");
            if (!tapEffortRefresh(12, 0.6d)) {
                throw new FlowException("未能找到预约/购买入口");
            }
            if (!tapPurchaseButton()) {
                throw new FlowException("未能找到预约/购买入口");
            }
        }
        tapEffortRefresh(12, 0.6d);

        // 3) 选择票价
        ensureNotStopped();
        dismissBlockingDialogs();
        if (config.priceIndex != null) {
            transitionTo(Phase.SELECTING_PRICE);
            log(LogLevel.STEP, "选择票价");
            selectPrice();
        }

        // 4) 选择数量
        ensureNotStopped();
        if (config.users.size() > 1) {
            transitionTo(Phase.SELECTING_QUANTITY);
            log(LogLevel.STEP, "选择数量");
            selectQuantity();
        }

        // 5) 确认购买
        ensureNotStopped();
        dismissBlockingDialogs();
        transitionTo(Phase.CONFIRMING_PURCHASE);
        log(LogLevel.STEP, "确认购买");
        if (!confirmPurchase()) {
            throw new FlowException("未能进入确认页面");
        }
        for (int i = 0; i < 8; i++) {
            ensureNotStopped();
            if (!tapEffortRefresh(1, 0.6d)) {
                break;
            }
            NodeFinder.sleep(300L);
            confirmPurchase();
        }

        // 6) 选择观演人
        ensureNotStopped();
        dismissBlockingDialogs();
        if (!config.users.isEmpty()) {
            transitionTo(Phase.SELECTING_USERS);
            log(LogLevel.STEP, "选择观演人");
            selectUsers(config.users);
        }

        // 7) 提交订单
        ensureNotStopped();
        transitionTo(Phase.SUBMITTING_ORDER);
        log(LogLevel.STEP, "提交订单");
        submitOrder();

        transitionTo(Phase.COMPLETED);
    }

    // ------------------------------------------------------------------
    // 弹窗处理（真机必备）
    // ------------------------------------------------------------------

    /**
     * 大麦 App 在购票链路上会插入若干「阻断式弹窗」，
     * 未处理时点击「立即购票」后页面不会前进。
     *
     * 实测（大麦 9.0.28）遇到的弹窗：
     *   1) 票务须知        —— 按钮 id: cn.damai:id/damai_theme_dialog_confirm_btn（确认并知悉）
     *   2) 实名制观演       —— confirm_btn（预选实名观演人）/ cancel_btn（知道了）
     *   3) 其它通用提示     —— 可能只有「知道了 / 我知道了 / 确定 / 取消」
     *
     * 这里统一按「确认类」优先、「知道了」次之的顺序尝试关闭，
     * 直到界面上不再出现已知弹窗。
     */
    private static final String DIALOG_CONFIRM_ID = "cn.damai:id/damai_theme_dialog_confirm_btn";
    private static final String DIALOG_CANCEL_ID = "cn.damai:id/damai_theme_dialog_cancel_btn";
    private static final String DIALOG_TITLE_ID = "cn.damai:id/damai_theme_dialog_title";

    /** 关闭当前页面上出现的阻断弹窗；返回是否关闭过至少一个。 */
    private boolean dismissBlockingDialogs() throws StoppedException {
        boolean handled = false;
        for (int round = 0; round < 4; round++) {
            ensureNotStopped();
            if (!hasAnyDialog()) {
                break;
            }
            String title = dialogTitle();
            // 优先「知道了」这类无副作用按钮；否则点确认按钮
            AccessibilityNodeInfo dismissed = null;
            NodeFinder.Selector[] safeButtons = new NodeFinder.Selector[]{
                    NodeFinder.Selector.textContains("知道了"),
                    NodeFinder.Selector.textContains("我知道了"),
                    NodeFinder.Selector.textContains("取消"),
            };
            dismissed = finder.waitForAny(500L, 50L, safeButtons);
            if (dismissed == null) {
                dismissed = finder.waitForAny(
                        500L, 50L,
                        NodeFinder.Selector.id(DIALOG_CONFIRM_ID),
                        NodeFinder.Selector.textContains("确认并知悉"),
                        NodeFinder.Selector.textContains("确定"),
                        NodeFinder.Selector.textContains("同意"));
            }
            if (dismissed == null && !safeButtonsMissing()) {
                break;
            }
            if (dismissed != null && finder.clickNode(dismissed)) {
                handled = true;
                log(LogLevel.INFO, "已关闭弹窗" + (title.isEmpty() ? "" : ": " + title));
                NodeFinder.sleep(400L);
            } else {
                break;
            }
        }
        return handled;
    }

    /** 是否存在大麦样式弹窗（按标题 id 判断）。 */
    private boolean hasAnyDialog() {
        return finder.findFirst(NodeFinder.Selector.id(DIALOG_TITLE_ID),
                NodeFinder.Selector.id(DIALOG_CONFIRM_ID)) != null;
    }

    private boolean safeButtonsMissing() {
        return finder.findFirst(
                NodeFinder.Selector.textContains("知道了"),
                NodeFinder.Selector.textContains("确认并知悉"),
                NodeFinder.Selector.textContains("确定")) == null;
    }

    private String dialogTitle() {
        AccessibilityNodeInfo t = finder.findFirst(NodeFinder.Selector.id(DIALOG_TITLE_ID));
        if (t == null || t.getText() == null) {
            return "";
        }
        return t.getText().toString().trim();
    }

    /**
     * 点击一个「点击后页面会变化」的入口（如立即购票 / 确认购买）。
     *
     * 真实设备上这类按钮点击后会立刻弹窗或跳页，
     * 因此：
     *   1) 用异步手势点击，避免页面切换导致手势被取消而误判失败；
     *   2) 点击后清理弹窗；
     *   3) 等待页面稳定，确保后续步骤在新页面上执行。
     */
    private boolean clickAndSettle(AccessibilityNodeInfo node, String label) throws StoppedException {
        if (node == null) {
            return false;
        }
        android.graphics.Rect r = NodeFinder.boundsOf(node);
        if (r.width() <= 0 || r.height() <= 0) {
            return false;
        }
        finder.tapVia(r.centerX(), r.centerY());
        NodeFinder.sleep(600L);
        dismissBlockingDialogs();
        finder.waitForStable(4000L, 500L);
        dismissBlockingDialogs();
        if (notBlank(label)) {
            log(LogLevel.INFO, "已点击“" + label + "”");
        }
        return true;
    }

    // ------------------------------------------------------------------
    // 交互原语
    // ------------------------------------------------------------------

    /** 依次尝试多个定位条件并点击（等价 _smart_wait_and_click）。 */
    private boolean smartWaitAndClick(NodeFinder.Selector primary, NodeFinder.Selector[] backups, long timeoutMs)
            throws StoppedException {
        List<NodeFinder.Selector> all = new ArrayList<NodeFinder.Selector>();
        all.add(primary);
        if (backups != null) {
            for (NodeFinder.Selector s : backups) {
                all.add(s);
            }
        }
        for (int idx = 0; idx < all.size(); idx++) {
            ensureNotStopped();
            // 首选选择器用完整 timeout，兜底用更短时间快速失败（同 Python 侧策略）
            long wait = idx == 0 ? timeoutMs : Math.min(timeoutMs, 600L);
            AccessibilityNodeInfo hit = finder.waitForAny(wait, 50L, all.get(idx));
            if (hit != null && finder.clickNode(hit)) {
                return true;
            }
        }
        return false;
    }

    private boolean ultraFastClick(NodeFinder.Selector sel, long timeoutMs) {
        AccessibilityNodeInfo hit = finder.waitForAny(timeoutMs, 50L, sel);
        return hit != null && finder.clickNode(hit);
    }

    /**
     * 循环检测并点击指定文本的按钮，直到按钮消失或达到次数上限。
     * 等价 _tap_text_loop：每个文本生成三组定位器（精确 / contains / 正则）。
     */
    private boolean tapTextLoop(List<String> texts, int maxTaps, double intervalSec, String label)
            throws StoppedException {
        List<NodeFinder.Selector> selectors = new ArrayList<NodeFinder.Selector>();
        for (String t : texts) {
            selectors.add(NodeFinder.Selector.text(t));
            selectors.add(NodeFinder.Selector.textContains(t));
            selectors.add(NodeFinder.Selector.textMatches(".*" + java.util.regex.Pattern.quote(t) + ".*"));
        }

        boolean clicked = false;
        for (int attempt = 0; attempt < maxTaps; attempt++) {
            ensureNotStopped();
            AccessibilityNodeInfo hit;
            if (attempt == 0) {
                hit = finder.waitForAny(300L, 50L, selectors.toArray(new NodeFinder.Selector[0]));
            } else {
                hit = finder.findFirst(selectors.toArray(new NodeFinder.Selector[0]));
            }
            if (hit == null) {
                break; // 按钮消失：已进入下一状态
            }
            if (finder.clickNode(hit)) {
                clicked = true;
                log(LogLevel.INFO, "已点击“" + label + "”按钮");
            } else {
                log(LogLevel.WARNING, "点击“" + label + "”失败");
                break;
            }
            NodeFinder.sleep((long) (intervalSec * 1000L));
        }
        return clicked;
    }

    // ------------------------------------------------------------------
    // 流程步骤
    // ------------------------------------------------------------------

    private boolean selectCity(String city) throws StoppedException {
        NodeFinder.Selector[] selectors = new NodeFinder.Selector[]{
                NodeFinder.Selector.text(city),
                NodeFinder.Selector.textContains(city),
        };
        // 快速探测：直接查找，不做长等待（同 Python 侧策略）
        AccessibilityNodeInfo hit = finder.findFirst(selectors);
        if (hit == null) {
            return false;
        }
        return finder.clickNode(hit);
    }

    private boolean tapPurchaseButton() throws StoppedException {
        // 真实大麦（9.x）的购买入口是「自定义绘制」的 FrameLayout：
        //   id = trade_project_detail_purchase_status_bar_container_fl，但 clickable=false、无文本，
        // 因此不能依赖 clickable 或文本，必须按其 bounds 中点做坐标点击。
        NodeFinder.Selector container = NodeFinder.Selector.id(
                "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl");
        AccessibilityNodeInfo bar = finder.waitForAny(waitMs(), 50L, container);
        if (bar != null && clickAndSettle(bar, "立即购票")) {
            return true;
        }
        // 兜底：文本型入口（旧版本 / 预约场景）
        NodeFinder.Selector[] backups = new NodeFinder.Selector[]{
                NodeFinder.Selector.textContains("立即购买"),
                NodeFinder.Selector.textContains("立即购票"),
                NodeFinder.Selector.textContains("购买"),
                NodeFinder.Selector.textContains("预约抢票"),
                NodeFinder.Selector.textContains("去抢票"),
                NodeFinder.Selector.textMatches(".*预约.*|.*立即.*"),
        };
        for (NodeFinder.Selector sel : backups) {
            ensureNotStopped();
            AccessibilityNodeInfo hit = finder.waitForAny(600L, 50L, sel);
            if (hit != null && clickAndSettle(hit, "购买入口")) {
                return true;
            }
        }
        return false;
    }

    private boolean tapEffortRefresh(int maxTaps, double intervalSec) throws StoppedException {
        List<String> texts = new ArrayList<String>();
        texts.add("努力刷新");
        return tapTextLoop(texts, maxTaps, intervalSec, "努力刷新");
    }

    private boolean tapContinueTry(int maxTaps, double intervalSec) throws StoppedException {
        List<String> texts = new ArrayList<String>();
        texts.add("继续尝试");
        return tapTextLoop(texts, maxTaps, intervalSec, "继续尝试");
    }

    private void selectPrice() throws StoppedException {
        if (config.priceIndex == null && !notBlank(config.price)) {
            return;
        }
        String[] containerIds = new String[]{
                "cn.damai:id/project_detail_perform_price_flowlayout",
                "cn.damai:id/project_detail_perform_price_flowLayout",
                "cn.damai:id/project_detail_perform_price_layout",
        };

        AccessibilityNodeInfo container = null;
        // 进入票档页可能仍残留弹窗，先清一遍再等容器
        dismissBlockingDialogs();
        for (int attempt = 0; attempt < 3 && container == null; attempt++) {
            for (int i = 0; i < containerIds.length; i++) {
                long wait = attempt == 0 && i == 0 ? waitMs() : 800L;
                container = finder.waitForAny(wait, 50L, NodeFinder.Selector.id(containerIds[i]));
                if (container != null) {
                    break;
                }
            }
            if (container == null) {
                dismissBlockingDialogs();
            }
        }
        if (container == null) {
            log(LogLevel.WARNING, "未找到票价容器，跳过票价选择");
            return;
        }

        AccessibilityNodeInfo target = null;
        // 优先按索引选择可点击的票价项
        if (config.priceIndex != null) {
            List<AccessibilityNodeInfo> items = clickableChildren(container);
            int idx = config.priceIndex;
            if (idx >= 0 && idx < items.size()) {
                target = items.get(idx);
            } else {
                log(LogLevel.WARNING, "票价索引 " + idx + " 超出范围（共 " + items.size() + " 项）");
            }
        }
        // 兜底：按票价文本选择
        if (target == null && notBlank(config.price)) {
            NodeFinder.Selector[] textSels = new NodeFinder.Selector[]{
                    NodeFinder.Selector.text(config.price),
                    NodeFinder.Selector.textContains(config.price),
            };
            target = NodeFinder.findInSubtree(container, textSels[0]);
            if (target == null) {
                target = NodeFinder.findInSubtree(container, textSels[1]);
            }
        }

        if (target == null) {
            log(LogLevel.WARNING, "未找到目标票价项，跳过票价选择");
            return;
        }

        // 目标不在可视范围时在容器内滚动
        int attempts = 0;
        Rect crect = NodeFinder.boundsOf(container);
        while (attempts < 5 && !isVisible(target)) {
            finder.scrollDown(crect, 0.8f);
            attempts++;
            NodeFinder.sleep(50L);
        }

        if (clickAndSettle(target, "票档")) {
            log(LogLevel.INFO, "票价选择完成");
        } else {
            log(LogLevel.WARNING, "票价选择点击失败");
        }
    }

    /** 收集容器内可点击的子项（对应 FrameLayout[@clickable=true] 的票价档位）。 */
    private List<AccessibilityNodeInfo> clickableChildren(AccessibilityNodeInfo container) {
        List<AccessibilityNodeInfo> out = new ArrayList<AccessibilityNodeInfo>();
        if (container == null) {
            return out;
        }
        for (int i = 0; i < container.getChildCount(); i++) {
            AccessibilityNodeInfo child = container.getChild(i);
            if (child != null && child.isClickable()) {
                out.add(child);
            }
        }
        if (out.isEmpty()) {
            // 退化为任意非空子节点
            for (int i = 0; i < container.getChildCount(); i++) {
                AccessibilityNodeInfo child = container.getChild(i);
                if (child != null) {
                    out.add(child);
                }
            }
        }
        return out;
    }

    private boolean isVisible(AccessibilityNodeInfo node) {
        if (node == null) {
            return false;
        }
        Rect r = NodeFinder.boundsOf(node);
        return r.width() > 0 && r.height() > 0 && !r.isEmpty();
    }

    private void selectQuantity() throws StoppedException {
        List<AccessibilityNodeInfo> toggles = new ArrayList<AccessibilityNodeInfo>();
        // 统计可点击的观演人切换控件
        String[] classes = new String[]{
                "android.widget.CheckBox",
                "android.widget.RadioButton",
                "android.widget.Switch",
                "android.widget.ImageView",
        };
        for (String cls : classes) {
            List<AccessibilityNodeInfo> found = finder.findElements(NodeFinder.Selector.className(cls));
            for (AccessibilityNodeInfo n : found) {
                if (n.isClickable()) {
                    toggles.add(n);
                }
            }
        }
        int desiredQty = Math.max(1, toggles.size());
        if (desiredQty <= 1) {
            return;
        }
        AccessibilityNodeInfo plus = finder.findFirst(
                NodeFinder.Selector.id("img_jia"),
                NodeFinder.Selector.id("cn.damai:id/img_jia"));
        if (plus == null) {
            return;
        }
        Rect r = NodeFinder.boundsOf(plus);
        for (int i = 0; i < desiredQty - 1; i++) {
            ensureNotStopped();
            finder.clickAt(r.centerX(), r.centerY(), 50L);
            NodeFinder.sleep(20L);
        }
    }

    private boolean confirmPurchase() throws StoppedException {
        // 真实大麦的「确定」按钮 id = btn_buy_view（同为自定义绘制，clickable=false）
        NodeFinder.Selector confirm = NodeFinder.Selector.id("btn_buy_view");
        AccessibilityNodeInfo btn = finder.waitForAny(waitMs(), 50L, confirm);
        if (btn != null && clickAndSettle(btn, "确定")) {
            return true;
        }
        AccessibilityNodeInfo byText = finder.waitForAny(800L, 50L,
                NodeFinder.Selector.textContains("确定"),
                NodeFinder.Selector.textContains("立即购买"),
                NodeFinder.Selector.textContains("提交"));
        return byText != null && clickAndSettle(byText, "确定");
    }

    private void selectUsers(List<String> users) throws StoppedException {
        if (users == null || users.isEmpty()) {
            log(LogLevel.WARNING, "未配置观演人，跳过选择");
            return;
        }
        Rect window = windowRect();

        for (String user : users) {
            boolean found = false;
            int attempts = 0;
            while (attempts < 6 && !found) {
                ensureNotStopped();
                try {
                    // 方式1：按 resource-id 精确定位观演人条目
                    AccessibilityNodeInfo item = findUserItem(user);
                    if (item != null) {
                        AccessibilityNodeInfo checkbox = NodeFinder.findInSubtree(
                                item, NodeFinder.Selector.id("checkbox"));
                        if (checkbox != null && NodeFinder.isChecked(checkbox)) {
                            log(LogLevel.INFO, "观演人已勾选，无需操作: " + user);
                            found = true;
                            continue;
                        }
                        if (checkbox != null && finder.clickNode(checkbox)) {
                            found = true;
                            NodeFinder.sleep(20L);
                            continue;
                        }
                        if (finder.clickNode(item)) {
                            found = true;
                            NodeFinder.sleep(20L);
                            continue;
                        }
                    }

                    // 方式2：退回姓名文本匹配
                    AccessibilityNodeInfo elem = finder.findFirst(
                            NodeFinder.Selector.text(user),
                            NodeFinder.Selector.textContains(user));
                    if (elem != null) {
                        AccessibilityNodeInfo row = NodeFinder.clickableAncestor(elem);
                        AccessibilityNodeInfo checkable = row != null ? row : elem;
                        if (NodeFinder.isChecked(checkable)) {
                            log(LogLevel.INFO, "观演人已勾选，无需操作: " + user);
                            found = true;
                            continue;
                        }
                        if (finder.clickNode(row != null ? row : elem)) {
                            found = true;
                            NodeFinder.sleep(20L);
                            continue;
                        }
                    }
                } catch (Exception e) {
                    log(LogLevel.WARNING, "选择观演人异常: " + user + " | " + e);
                }

                if (!found) {
                    finder.scrollDown(window, 0.5f);
                    attempts++;
                    NodeFinder.sleep(50L);
                }
            }
            if (!found) {
                log(LogLevel.WARNING, "未能选择观演人: " + user);
            }
        }
    }

    /** 定位观演人条目：优先 cn.damai:id/layout_main 内包含姓名 text_name 的父节点。 */
    private AccessibilityNodeInfo findUserItem(String user) {
        // 1) 先按姓名文本找到 text_name，再向上找 layout_main 条目
        AccessibilityNodeInfo nameNode = finder.findFirst(
                NodeFinder.Selector.text(user),
                NodeFinder.Selector.textContains(user));
        if (nameNode == null) {
            return null;
        }
        AccessibilityNodeInfo cur = nameNode;
        int guard = 0;
        while (cur != null && guard++ < 12) {
            String id = cur.getViewIdResourceName();
            if (id != null && id.endsWith(":id/layout_main")) {
                return cur;
            }
            cur = cur.getParent();
        }
        // 2) 退回最近的可点击祖先
        return NodeFinder.clickableAncestor(nameNode);
    }

    private void submitOrder() throws StoppedException {
        dismissBlockingDialogs();
        if (!config.ifCommitOrder) {
            log(LogLevel.INFO, "未开启自动提交订单，流程到此为止（请手动确认支付）");
            return;
        }
        NodeFinder.Selector primary = NodeFinder.Selector.text("立即提交");
        NodeFinder.Selector[] backups = new NodeFinder.Selector[]{
                NodeFinder.Selector.textMatches(".*提交.*|.*确认.*"),
                NodeFinder.Selector.textContains("提交"),
        };
        AccessibilityNodeInfo submit = finder.waitForAny(waitMs(), 50L, primary);
        if (submit != null) {
            clickAndSettle(submit, "立即提交");
        } else {
            for (NodeFinder.Selector sel : backups) {
                AccessibilityNodeInfo hit = finder.waitForAny(600L, 50L, sel);
                if (hit != null) {
                    clickAndSettle(hit, "提交");
                    break;
                }
            }
        }

        // 提交后若弹出“继续尝试”，循环关闭并重新提交
        for (int i = 0; i < 5; i++) {
            ensureNotStopped();
            if (!tapContinueTry(1, 0.5d)) {
                break;
            }
            NodeFinder.sleep(300L);
            smartWaitAndClick(primary, backups, waitMs());
        }
    }

    private Rect windowRect() {
        try {
            AccessibilityNodeInfo r = finder.root();
            if (r != null) {
                Rect rect = NodeFinder.boundsOf(r);
                if (rect.width() > 0 && rect.height() > 0) {
                    return rect;
                }
            }
        } catch (Exception ignored) {
            // 忽略：使用默认窗口
        }
        android.util.DisplayMetrics dm = service.getResources().getDisplayMetrics();
        return new Rect(0, 0, dm.widthPixels, dm.heightPixels);
    }

    private static boolean notBlank(String s) {
        return s != null && !s.trim().isEmpty();
    }
}
