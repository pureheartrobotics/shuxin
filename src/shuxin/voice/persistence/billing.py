import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("shuxin.voice.persistence.billing")

CACHE_EXPIRY_SECONDS = 300  # 5分钟价格缓存

# 预设的默认计费价格（当数据库尚未初始化或配置不存在时作为兜底）
DEFAULT_PRICING = {
    "stt": {
        "tencent-realtime": 0.000200,
        "default": 0.000200
    },
    "tts": {
        "volcengine-clone": 0.000020,
        "default": 0.000020
    },
    "llm": {
        "deepseek-chat": 0.000002,
        "default": 0.000002
    }
}


class BillingService:
    """初心框架异步计费与消费账单服务"""

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        # 缓存结构: { service_type: { model_name: price } }
        self._price_cache: Dict[str, Dict[str, float]] = {}
        # 缓存更新时间: { service_type: timestamp }
        self._cache_updated_at: Dict[str, float] = {}

    async def get_prices(self, service_type: str) -> Dict[str, float]:
        """获取某服务类型的定价字典（含5分钟内存缓存）"""
        now = time.time()
        cached_prices = self._price_cache.get(service_type)
        updated_at = self._cache_updated_at.get(service_type, 0.0)

        if cached_prices is not None and (now - updated_at) < CACHE_EXPIRY_SECONDS:
            return cached_prices

        # 缓存过期或不存在，从数据库加载
        try:
            prices = await self.repo.get_pricing_by_type(service_type)
            if not prices:
                # 数据库中没有对应的配置，使用默认预设值
                prices = DEFAULT_PRICING.get(service_type, {}).copy()
        except Exception as exc:
            logger.warning(
                "Failed to fetch pricing from repository for %s, using fallback: %s",
                service_type,
                exc
            )
            prices = DEFAULT_PRICING.get(service_type, {}).copy()

        self._price_cache[service_type] = prices
        self._cache_updated_at[service_type] = now
        return prices

    def calculate_cost(self, service_type: str, model_name: str, amount: float, prices: Dict[str, float]) -> float:
        """根据单价与用量计算支出（元）"""
        # 精确匹配模型单价，如果不存在则使用 default，否则使用预设的 default 兜底
        price = prices.get(model_name)
        if price is None:
            price = prices.get("default")
        if price is None:
            price = DEFAULT_PRICING.get(service_type, {}).copy().get("default", 0.0)

        # 保留小数点后 6 位，对极小开销（如单 token）更精确
        return round(float(amount) * float(price), 6)

    async def calculate_and_record(
        self,
        user_id: str,
        service_type: str,
        model_name: str,
        usage_amount: float
    ) -> None:
        """执行计费换算并入库写入"""
        if usage_amount <= 0:
            return

        # 获取当前服务的价格列表
        prices = await self.get_prices(service_type)
        cost_yuan = self.calculate_cost(service_type, model_name, usage_amount, prices)

        # 写入数据库流水明细
        await self.repo.insert_expenditure(
            user_id=user_id,
            service_type=service_type,
            model_name=model_name,
            usage_amount=usage_amount,
            cost_yuan=cost_yuan
        )
        logger.debug(
            "Recorded expenditure: user=%s, type=%s, model=%s, amount=%s, cost=%s",
            user_id, service_type, model_name, usage_amount, cost_yuan
        )

    def record_usage_in_background(
        self,
        user_id: str,
        *,
        device_id: Optional[str] = None,
        stt_seconds: float = 0.0,
        stt_model: str = "",
        llm_tokens: int = 0,
        llm_model: str = "",
        tts_chars: int = 0,
        tts_model: str = ""
    ) -> None:
        """非阻塞异步后台记账入口"""
        async def _run() -> None:
            try:
                # 1. 记录分钟数额度扣减
                cost_minutes = (stt_seconds + tts_chars * 0.25) / 60.0
                if cost_minutes > 0:
                    try:
                        target_device_id = device_id
                        if not target_device_id and hasattr(self.repo, "get_user_quota_by_user_id"):
                            quota = await self.repo.get_user_quota_by_user_id(user_id)
                            target_device_id = quota.get("device_id")

                        if target_device_id and hasattr(self.repo, "deduct_device_minutes_quota"):
                            await self.repo.deduct_device_minutes_quota(target_device_id, cost_minutes)
                            logger.debug("Deducted device minutes quota: device=%s, cost_minutes=%s", target_device_id, cost_minutes)
                        elif hasattr(self.repo, "deduct_user_minutes_quota"):
                            await self.repo.deduct_user_minutes_quota(user_id, cost_minutes)
                            logger.debug("Deducted user minutes quota: user=%s, cost_minutes=%s", user_id, cost_minutes)
                    except Exception as quota_exc:
                        logger.error("Failed to deduct minutes quota for user %s/device %s: %s", user_id, device_id, quota_exc)

                # 2. 记录 STT 消费
                if stt_seconds > 0:
                    await self.calculate_and_record(
                        user_id=user_id,
                        service_type="stt",
                        model_name=stt_model or "default",
                        usage_amount=stt_seconds
                    )

                # 3. 记录 LLM 消费
                if llm_tokens > 0:
                    await self.calculate_and_record(
                        user_id=user_id,
                        service_type="llm",
                        model_name=llm_model or "default",
                        usage_amount=llm_tokens
                    )

                # 4. 记录 TTS 消费
                if tts_chars > 0:
                    await self.calculate_and_record(
                        user_id=user_id,
                        service_type="tts",
                        model_name=tts_model or "default",
                        usage_amount=tts_chars
                    )
            except Exception as exc:
                logger.error(
                    "Failed to record expenditures in background for user %s: %s",
                    user_id,
                    exc,
                    exc_info=True
                )

        # 创建后台异步任务，对核心会话流程完全非阻塞
        asyncio.create_task(_run())
        logger.debug("Spawned background expenditure task for user %s, device %s", user_id, device_id)

    def invalidate_cache(self, service_type: str = "") -> None:
        """清除缓存（当管理员修改价格配置后应调用此方法刷新配置）"""
        if service_type:
            self._price_cache.pop(service_type, None)
            self._cache_updated_at.pop(service_type, None)
            logger.info("Invalidated billing cache for service type: %s", service_type)
        else:
            self._price_cache.clear()
            self._cache_updated_at.clear()
            logger.info("Invalidated all billing cache")
