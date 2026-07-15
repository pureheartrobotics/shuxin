import { request } from "../../../core/http";
import { requireSession } from "../../../core/auth";

export type PaymentPlan = {
  id: string;
  name: string;
  description?: string;
  amount_fen: number;
  amount_yuan: number;
  add_yuan: number;
  duration_days: number;
};

export async function fetchPaymentPlans(): Promise<PaymentPlan[]> {
  const data = await request<{ items: PaymentPlan[] }>("/api/payment/plans", { method: "GET" });
  return Array.isArray(data.items) ? data.items : [];
}

export async function createQuotaOrder(planId: string) {
  const session_token = requireSession();
  return request("/api/payment/create-order", {
    method: "POST",
    data: { session_token, plan_id: planId },
  });
}

export function invokeWechatPay(payParams: Record<string, unknown>): Promise<void> {
  return new Promise((resolve, reject) => {
    uni.requestPayment({
      provider: "wxpay",
      timeStamp: String(payParams.timeStamp || ""),
      nonceStr: String(payParams.nonceStr || ""),
      package: String(payParams.package || ""),
      signType: String(payParams.signType || "RSA"),
      paySign: String(payParams.paySign || ""),
      success: () => resolve(),
      fail: (error) => reject(new Error(error.errMsg || "支付失败")),
    });
  });
}
