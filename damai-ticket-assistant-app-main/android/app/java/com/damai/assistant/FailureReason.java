package com.damai.assistant;

/** 失败原因（与 Python 侧 FailureReason 对齐）。 */
public final class FailureReason {
    public static final String USER_STOP = "user_stop";
    public static final String SERVICE_UNAVAILABLE = "accessibility_service_unavailable";
    public static final String FLOW_FAILURE = "flow_failure";
    public static final String UNEXPECTED = "unexpected_error";
    public static final String MAX_RETRIES = "max_retries_reached";

    private FailureReason() {
    }
}
