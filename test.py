import time
import random
import tracemalloc
import sys

def compare_indexing(data_size: int, num_queries: int = 10000):
    """
    比较列表与字典的索引性能（时间和空间）
    
    参数:
        data_size: 数据量（列表长度 / 字典键值对数量）
        num_queries: 随机索引测试的次数
    """
    # 确保随机索引在有效范围内
    random.seed(42)
    indices = [random.randint(0, data_size - 1) for _ in range(num_queries)]
    
    # ---------- 内存测量 ----------
    # 测量列表内存
    tracemalloc.start()
    lst = list(range(data_size))          # 创建列表
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    lst_mem = peak  # 峰值内存（字节），更接近实际分配
    # 测量字典内存
    tracemalloc.start()
    dct = {i: i for i in range(data_size)} # 创建字典
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    dct_mem = peak

    # 也可用 sys.getsizeof 获取浅层大小（仅供参考）
    lst_shallow = sys.getsizeof(lst)
    dct_shallow = sys.getsizeof(dct)

    # ---------- 索引时间测量 ----------
    # 列表索引
    start = time.perf_counter()
    for idx in indices:
        _ = lst[idx]         # 访问元素，避免优化
    end = time.perf_counter()
    list_time = (end - start) / num_queries   # 平均每次访问时间（秒）

    # 字典索引
    start = time.perf_counter()
    for key in indices:
        _ = dct[key]
    end = time.perf_counter()
    dict_time = (end - start) / num_queries

    # ---------- 打印比较结果 ----------
    print(f"数据规模: {data_size} 个元素")
    print("=" * 50)
    print("【内存占用】")
    print(f"列表 (峰值内存) : {lst_mem / 1024:.2f} KB")
    print(f"字典 (峰值内存) : {dct_mem / 1024:.2f} KB")
    print(f"列表 (浅层大小) : {lst_shallow} 字节")
    print(f"字典 (浅层大小) : {dct_shallow} 字节")
    print("【索引时间】（平均每次访问）")
    print(f"列表 : {list_time * 1e6:.2f} 微秒")
    print(f"字典 : {dict_time * 1e6:.2f} 微秒")
    print(f"时间比 (字典/列表) : {dict_time / list_time:.2f}")
    print()


if __name__ == "__main__":
    # 测试不同规模的数据
    compare_indexing(100)
    compare_indexing(100000)
    compare_indexing(1000000)   # 一百万（注意内存消耗）