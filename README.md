# 本地 Level-2 连续研究报告

基于本地沪深 A 股 Level-2、日线和分钟线生成交互报告。仅用于研究，不构成交易授权。

## 启动

需要 Python 及 `duckdb`、`pandas`。将 `level2_paths.example.json` 复制为同目录 `level2_paths.json`，填写实际绝对路径。配置修改后重启服务。

首次运行需先生成基准报告（当前服务默认基准日为 20260922，需对应正式数据及提交标识）：

```sh
python generate_level2_report.py
python level2_detail_server.py
```

访问 http://127.0.0.1:18762/level2-market-scan_20260922.html 。服务仅监听本机，可选择其他有完整数据的日期生成报告。生成器的默认日期回归断言针对本项目已核验的数据，并非通用任意日期启动器。

## 功能与边界

- 全市场日级扫描、候选筛选排序、个股按需深查。
- 本地日K／分钟K及成交量；本地最新读取不是交易所实时行情。
- 日期报告与只读快照；仅冻结已加载的图表。
- 连续状态、可逐日调整的观察窗口及事件观察仍属设计，详见 `Level2数据实战使用框架.md`，不能视为已实现。

原始行情、本机配置、缓存、生成报告、快照及其他研究文件不纳入仓库。首次克隆不会附带可直接浏览的业务数据。

## 验证

```sh
python -m unittest test_level2_workspace test_level2_detail test_level2_kline test_level2_intraday test_level2_chart_axis test_level2_fresh_chart
python validate_level2_report.py
```

测试前需建立本机路径配置；报告校验还要求先生成基准报告。
