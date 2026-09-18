package cn.damai;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.CheckBox;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * 大麦 App 的测试替身。
 *
 * 复刻真实大麦购票流程的页面结构与 view-id，用于在无法安装真实大麦 App
 * 的环境（如离线模拟器）中验证「大麦抢票助手」的自动化流程是否可用。
 *
 * 页面流转：
 *   STAGE_DETAIL(详情页)  --点击购买-->  STAGE_PRICE(票价页)
 *   --选中票价-->  STAGE_CONFIRM(确认页)  --点击 btn_buy_view-->  STAGE_ORDER(订单页)
 *   --点击「立即提交」-->  STAGE_DONE
 *
 * 关键约定：控件的 view-id 与真实大麦 App 完全一致，
 * 因此 TicketRunner.java 中现成的选择器可直接命中。
 */
public class MainActivity extends Activity {

    private static final String TAG = "DamaiMock";

    /** 当前页面阶段，供脚本/adb 读取校验。 */
    public static final String STAGE_DETAIL = "detail";
    public static final String STAGE_PRICE = "price";
    public static final String STAGE_CONFIRM = "confirm";
    public static final String STAGE_ORDER = "order";
    public static final String STAGE_DONE = "done";

    /** 可配置的城市名（默认郑州，与常见测试配置一致）。 */
    private String city = "郑州";
    private String stage = STAGE_DETAIL;

    /**
     * 已勾选的观演人集合。
     * 真实大麦 App 会在二次进入确认订单页时保留上次的勾选状态，
     * 这里同样持久化，用于验证自动化「已勾选则跳过、不误取消」的幂等逻辑。
     */
    private final java.util.Set<String> selected = new java.util.HashSet<String>();

    private LinearLayout root;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String extraCity = getIntent().getStringExtra("city");
        if (extraCity != null && !extraCity.isEmpty()) {
            city = extraCity;
        }
        Log.i(TAG, "mock damai started, stage=" + stage + " city=" + city);
        render();
    }

    // ------------------------------------------------------------------
    // 渲染
    // ------------------------------------------------------------------

    private void render() {
        ScrollView scroll = new ScrollView(this);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(16), dp(16), dp(16));
        scroll.addView(root);

        if (STAGE_DETAIL.equals(stage)) {
            renderDetail();
        } else if (STAGE_PRICE.equals(stage)) {
            renderPrice();
        } else if (STAGE_CONFIRM.equals(stage)) {
            renderConfirm();
        } else if (STAGE_ORDER.equals(stage)) {
            renderOrder();
        } else {
            renderDone();
        }
        setContentView(scroll);
    }

    private void renderDetail() {
        root.addView(header("演出详情（测试替身）"));

        // 城市标签：自动化会查找文本 = city
        TextView cityTag = new TextView(this);
        cityTag.setText(city);
        cityTag.setTextSize(16);
        cityTag.setPadding(0, dp(8), 0, dp(8));
        root.addView(cityTag);

        root.addView(label("项目：测试演唱会"));
        root.addView(label("时间：2026-08-15 19:30"));

        // 购买入口：真实 id = cn.damai:id/trade_project_detail_purchase_status_bar_container_fl
        FrameLayout buyBar = new FrameLayout(this);
        buyBar.setId(R.id.trade_project_detail_purchase_status_bar_container_fl);
        buyBar.setClickable(true);
        buyBar.setBackgroundColor(Color.parseColor("#FF5722"));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(56));
        lp.setMargins(0, dp(16), 0, 0);
        TextView buyText = new TextView(this);
        buyText.setText("立即购买");
        buyText.setTextColor(Color.WHITE);
        buyText.setTextSize(17);
        buyText.setGravity(Gravity.CENTER);
        buyBar.addView(buyText);
        buyBar.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                goStage(STAGE_PRICE);
            }
        });
        root.addView(buyBar, lp);
    }

    private void renderPrice() {
        root.addView(header("选择票价（测试替身）"));

        // 票价容器：真实 id = cn.damai:id/project_detail_perform_price_flowlayout
        LinearLayout priceBox = new LinearLayout(this);
        priceBox.setId(R.id.project_detail_perform_price_flowlayout);
        priceBox.setOrientation(LinearLayout.VERTICAL);

        final String[] prices = {"看台280元", "看台380元", "内场580元", "VIP票388元"};
        for (int i = 0; i < prices.length; i++) {
            final int index = i;
            // 每个票档是一个可点击 FrameLayout 子项（与真实页面结构一致）
            FrameLayout item = new FrameLayout(this);
            item.setClickable(true);
            item.setBackgroundColor(i % 2 == 0
                    ? Color.parseColor("#EEEEEE") : Color.parseColor("#DDDDDD"));
            TextView t = new TextView(this);
            t.setText(prices[i]);
            t.setTextSize(16);
            t.setGravity(Gravity.CENTER);
            item.addView(t);
            LinearLayout.LayoutParams ilp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(52));
            ilp.setMargins(0, dp(6), 0, dp(6));
            item.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    Log.i(TAG, "price selected index=" + index + " text=" + prices[index]);
                    goStage(STAGE_CONFIRM);
                }
            });
            priceBox.addView(item, ilp);
        }
        root.addView(priceBox);
    }

    private void renderConfirm() {
        root.addView(header("确认购买（测试替身）"));
        root.addView(label("已选票价：VIP票388元"));
        root.addView(label("数量：1 张"));

        // 确认按钮：真实 id = cn.damai:id/btn_buy_view
        TextView confirm = new TextView(this);
        confirm.setId(R.id.btn_buy_view);
        confirm.setText("确定");
        confirm.setTextSize(17);
        confirm.setTextColor(Color.WHITE);
        confirm.setGravity(Gravity.CENTER);
        confirm.setClickable(true);
        confirm.setBackgroundColor(Color.parseColor("#FF9800"));
        confirm.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                goStage(STAGE_ORDER);
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(56));
        lp.setMargins(0, dp(16), 0, 0);
        root.addView(confirm, lp);
    }

    private void renderOrder() {
        root.addView(header("确认订单（测试替身）"));

        // 数量加号：真实 id = cn.damai:id/img_jia
        LinearLayout qtyRow = new LinearLayout(this);
        qtyRow.setOrientation(LinearLayout.HORIZONTAL);
        qtyRow.setGravity(Gravity.CENTER_VERTICAL);
        TextView qtyLabel = new TextView(this);
        qtyLabel.setText("购买数量：");
        qtyRow.addView(qtyLabel);
        TextView plus = new TextView(this);
        plus.setId(R.id.img_jia);
        plus.setText("  +  ");
        plus.setTextSize(20);
        plus.setClickable(true);
        plus.setBackgroundColor(Color.parseColor("#CCCCCC"));
        qtyRow.addView(plus);
        root.addView(qtyRow);

        // 观演人列表容器：真实 id = cn.damai:id/recycler_main
        LinearLayout viewerBox = new LinearLayout(this);
        viewerBox.setId(R.id.recycler_main);
        viewerBox.setOrientation(LinearLayout.VERTICAL);

        final String[] viewers = {"张三", "李四", "王五"};
        for (String name : viewers) {
            viewerBox.addView(buildViewerRow(name));
        }
        Log.i(TAG, "RENDER order page, selected=" + selected);
        LinearLayout.LayoutParams vlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        vlp.setMargins(0, dp(10), 0, dp(10));
        root.addView(viewerBox, vlp);

        // 提交按钮：真实文本 = 立即提交
        TextView submit = new TextView(this);
        submit.setText("立即提交");
        submit.setTextSize(17);
        submit.setTextColor(Color.WHITE);
        submit.setGravity(Gravity.CENTER);
        submit.setClickable(true);
        submit.setBackgroundColor(Color.parseColor("#4CAF50"));
        submit.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                goStage(STAGE_DONE);
            }
        });
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(56));
        slp.setMargins(0, dp(16), 0, 0);
        root.addView(submit, slp);
    }

    /** 构造一行观演人：外层 layout_main（可点击）内含 text_name 与 checkbox。 */
    private View buildViewerRow(final String name) {
        LinearLayout row = new LinearLayout(this);
        row.setId(R.id.layout_main);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setClickable(true);
        row.setPadding(dp(8), dp(8), dp(8), dp(8));

        final CheckBox cb = new CheckBox(this);
        cb.setId(R.id.checkbox);
        cb.setClickable(true);
        // 恢复上次的勾选状态（真实 App 二次进入时会保留）
        cb.setChecked(selected.contains(name));

        TextView nameView = new TextView(this);
        nameView.setId(R.id.text_name);
        nameView.setText(name);
        nameView.setTextSize(16);
        nameView.setPadding(dp(10), 0, 0, 0);

        // 点击整行即勾选，便于无障碍点击命中
        row.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                boolean next = !cb.isChecked();
                cb.setChecked(next);
                remember(name, next);
                Log.i(TAG, "ROW-click name=" + name + " -> " + next + " rowBounds=" + boundsOf(row)
                        + " cbBounds=" + boundsOf(cb));
            }
        });
        // 直接点击 CheckBox 本身时也要同步（自动化正是点击 checkbox 中心）
        cb.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                remember(name, cb.isChecked());
                Log.i(TAG, "CB-click name=" + name + " -> " + cb.isChecked()
                        + " cbBounds=" + boundsOf(cb));
            }
        });

        row.addView(cb);
        row.addView(nameView);

        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(4), 0, dp(4));
        row.setLayoutParams(lp);
        return row;
    }

    private void renderDone() {
        root.addView(header("提交成功（测试替身）"));
        root.addView(label("订单已提交，请前往支付。"));
        Log.i(TAG, "order submitted: stage=" + stage);
    }

    // ------------------------------------------------------------------
    // 工具
    // ------------------------------------------------------------------

    private String boundsOf(View v) {
        int[] loc = new int[2];
        v.getLocationOnScreen(loc);
        return "[" + loc[0] + "," + loc[1] + "][" + (loc[0] + v.getWidth()) + "," + (loc[1] + v.getHeight()) + "]";
    }

    /** 记录观演人勾选状态。 */
    private void remember(String name, boolean checked) {
        if (checked) {
            selected.add(name);
        } else {
            selected.remove(name);
        }
    }

    private void goStage(String next) {
        stage = next;
        Log.i(TAG, "stage -> " + stage);
        render();
    }

    private TextView header(String text) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextSize(20);
        v.setGravity(Gravity.CENTER_HORIZONTAL);
        return v;
    }

    private TextView label(String text) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextSize(15);
        v.setPadding(0, dp(4), 0, dp(4));
        return v;
    }

    private int dp(int value) {
        float density = getResources().getDisplayMetrics().density;
        return (int) (value * density + 0.5f);
    }
}
