import time
from llm.rate_limiter import GlobalRateLimiter


def test_rate_limiter_basic():
    """测试基本限流功能"""
    limiter = GlobalRateLimiter(min_interval=0.1)

    start = time.time()
    limiter.wait()
    limiter.wait()
    limiter.wait()
    elapsed = time.time() - start

    # 3 次调用至少间隔 0.2 秒
    assert elapsed >= 0.2


def test_rate_limiter_thread_safety():
    """测试线程安全"""
    import threading

    limiter = GlobalRateLimiter(min_interval=0.05)
    call_times = []

    def worker():
        limiter.wait()
        call_times.append(time.time())

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 检查调用间隔
    call_times.sort()
    for i in range(1, len(call_times)):
        interval = call_times[i] - call_times[i-1]
        assert interval >= 0.05 - 0.01  # 允许小误差
