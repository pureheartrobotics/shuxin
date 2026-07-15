import { ref } from "vue";
import {
  createQuotaOrder,
  fetchPaymentPlans,
  invokeWechatPay,
  type PaymentPlan,
} from "../api/payment-quota";
import { requireSession } from "../../../core/auth";

export function useQuotaPayment() {
  const paying = ref(false);
  const plansLoading = ref(false);
  const showPaymentSheet = ref(false);
  const plans = ref<PaymentPlan[]>([]);
  const message = ref("");

  async function openPaymentSheet() {
    showPaymentSheet.value = true;
    plansLoading.value = true;
    message.value = "";
    try {
      plans.value = await fetchPaymentPlans();
    } catch (error: any) {
      message.value = error.message || String(error);
      plans.value = [];
    } finally {
      plansLoading.value = false;
    }
  }

  function closePaymentSheet() {
    if (paying.value) return;
    showPaymentSheet.value = false;
  }

  async function purchasePlan(plan: PaymentPlan, onSuccess?: () => void) {
    requireSession();
    paying.value = true;
    message.value = "";
    try {
      const result: any = await createQuotaOrder(plan.id);
      await invokeWechatPay(result.pay_params || {});
      message.value = "支付成功，额度更新中";
      showPaymentSheet.value = false;
      if (onSuccess) await onSuccess();
    } catch (error: any) {
      const text = error.message || String(error);
      if (text.includes("无法重复购买")) {
        uni.showModal({
          title: "提示",
          content: text,
          showCancel: false,
          confirmText: "确定",
        });
      } else if (!text.includes("cancel")) {
        message.value = text;
      }
    } finally {
      paying.value = false;
    }
  }

  return {
    paying,
    plansLoading,
    showPaymentSheet,
    plans,
    message,
    openPaymentSheet,
    closePaymentSheet,
    purchasePlan,
  };
}
