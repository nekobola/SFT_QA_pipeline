"""全局限流器 — 令牌桶算法，支持突发并发

原 GlobalRateLimiter 使用单锁 + sleep，串行化所有线程。
令牌桶算法允许突发到 burst 上限，同时维持平均 rate，让 ThreadPool 真正生效。
"""

import time
import threading


class TokenBucketRateLimiter:
    """
    令牌桶限流器：以 rate 速度生成令牌，最多积累 burst 个。
    每次调用 wait() 消耗 1 个令牌；无令牌时阻塞等待。

    burst 应 >= max_concurrent_calls，以保证线程池能同时发出请求。
    """

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self.rate = float(rate)
        self.burst = float(burst)
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def wait(self):
        """获取 1 个令牌，必要时等待"""
        wait_time = 0.0
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
            else:
                wait_time = (1.0 - self.tokens) / self.rate
                self.tokens = 0.0

        if wait_time > 0:
            time.sleep(wait_time)


class GlobalRateLimiter(TokenBucketRateLimiter):
    """
    保持旧接口兼容的 GlobalRateLimiter。

    原接口: GlobalRateLimiter(min_interval=0.1)
    新接口: 内部转为 rate=1/min_interval, burst=max_concurrent_calls

    wait() 方法签名不变，旧代码无需修改。
    """

    def __init__(self, min_interval: float = 0.3, burst: int = 20):
        rate = 1.0 / min_interval if min_interval > 0 else 1000.0
        super().__init__(rate=rate, burst=burst)
