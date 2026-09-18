package com.damai.assistant;

/** 流程阶段（与 Python 侧 RunnerPhase 对齐）。 */
public final class Phase {
    public static final String INIT = "init";
    public static final String CONNECTING = "connecting";
    public static final String APPLYING_SETTINGS = "applying_settings";
    public static final String SELECTING_CITY = "selecting_city";
    public static final String TAPPING_PURCHASE = "tapping_purchase";
    public static final String SELECTING_PRICE = "selecting_price";
    public static final String SELECTING_QUANTITY = "selecting_quantity";
    public static final String CONFIRMING_PURCHASE = "confirming_purchase";
    public static final String SELECTING_USERS = "selecting_users";
    public static final String SUBMITTING_ORDER = "submitting_order";
    public static final String COMPLETED = "completed";
    public static final String STOPPED = "stopped";
    public static final String FAILED = "failed";

    private Phase() {
    }
}
