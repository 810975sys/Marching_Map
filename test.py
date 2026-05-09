import timeit

def benchmark_indexing_time(list_size=1_000_000, key_type='int', repeats=1_000_000):
    """
    测试列表下标索引与字典键索引的访问时间（仅读取操作）。

    参数:
        list_size : 列表 / 字典元素个数
        key_type  : 字典键类型，可选 'int' 或 'str'
        repeats   : 每种操作重复执行的次数（总操作数）
    """
    # ---------- 准备测试数据 ----------
    test_list = list(range(list_size))
    test_dict = {i: i for i in range(list_size)} if key_type == 'int' \
                else {str(i): i for i in range(list_size)}

    # 选取中间位置的索引 / 键，避免极端缓存效应
    index = list_size // 2
    key = index if key_type == 'int' else str(index)

    # ---------- 预热（可选，减少冷启动影响）----------
    _ = test_list[index]
    _ = test_dict[key]

    # ---------- 测量列表索引 ----------
    list_time = timeit.timeit(
        'test_list[index]',
        globals={'test_list': test_list, 'index': index},
        number=repeats
    )

    # ---------- 测量字典索引 ----------
    dict_time = timeit.timeit(
        'test_dict[key]',
        globals={'test_dict': test_dict, 'key': key},
        number=repeats
    )

    # ---------- 输出结果 ----------
    avg_list_ns = (list_time / repeats) * 1e9
    avg_dict_ns = (dict_time / repeats) * 1e9

    print(f"数据规模: {list_size:,} 元素, 每项重复 {repeats:,} 次")
    print(f"列表索引总耗时: {list_time:.6f} 秒  |  平均: {avg_list_ns:.2f} ns/次")
    print(f"字典索引总耗时: {dict_time:.6f} 秒  |  平均: {avg_dict_ns:.2f} ns/次")
    print(f"字典比列表慢: {dict_time / list_time:.2f} 倍")

if __name__ == '__main__':
    # 默认测试：整数键
    benchmark_indexing_time()
    # 改变规模与键类型
    benchmark_indexing_time(list_size=10_000_000, key_type='str', repeats=500_000)