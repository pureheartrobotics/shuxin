import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from shuxin.voice.persistence.billing import BillingService, DEFAULT_PRICING


class DummyRepo:
    def __init__(self):
        self.get_pricing_by_type = AsyncMock(return_value={})
        self.insert_expenditure = AsyncMock()


def test_billing_service_pricing_cache() -> None:
    async def run_test():
        repo = DummyRepo()
        service = BillingService(repo)

        # 1. 第一阶段：缓存不存在，应该调用库查询
        pricing_data = {"tencent-realtime": 0.000300, "default": 0.000250}
        repo.get_pricing_by_type.return_value = pricing_data

        prices = await service.get_prices("stt")
        assert prices == pricing_data
        repo.get_pricing_by_type.assert_called_once_with("stt")

        # 2. 第二阶段：缓存未过期，再次查询不应触发库查询
        repo.get_pricing_by_type.reset_mock()
        prices2 = await service.get_prices("stt")
        assert prices2 == pricing_data
        repo.get_pricing_by_type.assert_not_called()

        # 3. 第三阶段：手动清除缓存，再次查询应该重新触发库查询
        service.invalidate_cache("stt")
        repo.get_pricing_by_type.reset_mock()
        prices3 = await service.get_prices("stt")
        assert prices3 == pricing_data
        repo.get_pricing_by_type.assert_called_once_with("stt")

    asyncio.run(run_test())


def test_billing_service_cost_calculation() -> None:
    repo = DummyRepo()
    service = BillingService(repo)

    # 精确匹配价格
    prices = {"tencent-realtime": 0.0002, "default": 0.0001}
    cost = service.calculate_cost("stt", "tencent-realtime", 10.0, prices)
    assert cost == 0.002000

    # 兜底匹配 default
    cost_default = service.calculate_cost("stt", "unknown-model", 10.0, prices)
    assert cost_default == 0.001000

    # 空配置匹配兜底单价
    cost_fallback = service.calculate_cost("stt", "unknown", 10.0, {})
    assert cost_fallback == round(10.0 * DEFAULT_PRICING["stt"]["default"], 6)


def test_billing_service_async_record() -> None:
    async def run_test():
        repo = DummyRepo()
        service = BillingService(repo)

        pricing_data = {"tencent-realtime": 0.0002, "default": 0.0001}
        repo.get_pricing_by_type.return_value = pricing_data

        # 调用异步后台记录（不使用 await，因为它是 create_task 的 fire-and-forget 模式）
        service.record_usage_in_background(
            user_id="test_user",
            stt_seconds=15.0,
            stt_model="tencent-realtime",
            llm_tokens=1000,
            llm_model="deepseek-chat",
            tts_chars=100,
            tts_model="volcengine-clone"
        )

        # 等待微小间隔让后台异步任务执行完毕
        await asyncio.sleep(0.1)

        # 验证 repo 的写入被正确调用
        # 共有 3 个服务：STT (15秒 * 0.0002 = 0.003元)，LLM (1000 * 0.000002 = 0.002元)，TTS (100 * 0.00002 = 0.002元)
        assert repo.insert_expenditure.call_count == 3

        # 检查其中一个调用的参数
        repo.insert_expenditure.assert_any_call(
            user_id="test_user",
            service_type="stt",
            model_name="tencent-realtime",
            usage_amount=15.0,
            cost_yuan=0.003
        )

    asyncio.run(run_test())
