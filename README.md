# 认知智能前沿技术与实践 期末项目

预测 Anthropic 是否在 **2026年12月15日美东23:59前挂牌并开放交易**。

当前版本按**美东2026-10-14日终**补录，实际补录日期为2026-10-27。
最终意见池为 **75.6%（Yes）**，市场历史价格 **71.5%**，未校准证据模型 **82.0%**。
指定假设下的敏感性范围为 **68.1%–82.8%**，没有80%覆盖率保证。
算法和数据都已更新，不能把旧版79.4%到75.6%的变化全部归因于新闻。

## 从这里阅读

- [当前项目报告](docs/项目报告.md)：随流水线从forecast.json生成。
- [代码审查与优化记录](docs/代码审查与优化记录.md)：问题、修复与剩余局限。
- [10月14日补录记录](docs/2026-10-14补录.md)：来源、价格变化与时间口径。
- [当前算法原理](docs/项目原理说明.md)：公式与概率口径。
- [最终预测数据](data/processed/forecast.json)：schema_version=2。

10月7日原始产物、图表与文档完整保存在 `data/archive/2026-10-07/`。
`docs/`中原有两份Word仍为10月7日的历史排版稿，本次未重新排版，请以当前Markdown
报告为准。正式提交仍需Word或PDF、组号与成员姓名；正文不超过8页，参考文献与附件另算。

## 复现

Python 3.10+；本次验证环境为Python 3.13.5、NumPy 2.2.6、Matplotlib 3.10.5。

    python -m pip install -r requirements.txt
    python -X utf8 scripts/run_pipeline.py --as-of 2026-10-14
    python -X utf8 -m unittest discover -s tests -v

数据已保存，分析、出图、报告生成不需联网。可从任意目录用入口脚本的绝对路径运行。
固定种子20261007。入口会覆盖当前分析、图表与Markdown报告；历史留档请单独保存。

重新补采指定信息日：

    python -X utf8 scripts/backfill_market.py --as-of 2026-10-14
    python -X utf8 scripts/run_pipeline.py --as-of 2026-10-14

默认使用系统网络环境；需要本地代理时可设置：

    $env:PJ_PROXY = "http://127.0.0.1:7897"

`collect_polymarket.py --as-of ...`是补采入口的兼容别名。新版采集使用官方Data API v2、
显式时间范围、分页、有限重试和TLS证书验证。全部活跃节点采齐后才发布快照。
不覆盖原始Gamma快照，也不将当前盘口、成交量或流动性混入历史数据。

单个分析脚本支持环境变量 `PJ_AS_OF` 和 `PJ_PROCESSED`（输出目录）。
新信息日必须先补采，并核对事件是否已挂牌、当前流程与假设，不能只改日期就当成在线更新完成。

## 方法

![流程图](figures/fig0_pipeline.png)

1. 以合约标注日期构建期限CDF，保留原始价格与UTC元数据。
2. 证据模型模拟说明会、路演、定价与挂牌，处理节假日、延期和失败吸收态。
3. 市场拟合模型仅作诊断，12/15目标节点留出。
4. 最终将**未校准证据模型**与目标市场价格做log-odds意见池，模型权重0.35。
5. 输出概率分桶、条件情景、敏感性、7张图与当前报告。

两个来源可能共享新闻，意见池不声称独立。权重未做样本外验证，拟合损失不是预测准确率。
市场也能从期限CDF推算同类条件概率，中间日期需要插值或流程假设。

## 目录与职责

| 路径 | 内容 |
|---|---|
| `scripts/run_pipeline.py` | 一键离线复现 |
| `scripts/project_config.py` | 根目录、信息截止、合约日期 |
| `scripts/backfill_market.py` | 历史补采与原始响应留存 |
| `scripts/build_evidence_index.py` | 合并已保存新闻及核实补录 |
| `scripts/analyze_term_structure.py` | CDF、危险率、历史面板与跳变 |
| `scripts/model_core.py`、`exchange_calendar.py` | 模拟引擎与交易日历 |
| `scripts/milestone_model.py` | 不拟合市场的证据模型 |
| `scripts/calibrate_model.py` | 市场诊断、留出、意见池与情景 |
| `scripts/make_figures.py`、`make_pipeline_figure.py` | 生成7张图 |
| `scripts/build_report_markdown.py` | 当前报告模板及结果渲染 |
| `scripts/build_report_docx.py` | 原有Word构建器，导出后需检查排版 |
| `data/raw/backfill/2026-10-14/` | 原始响应、规范化价格、快照和采集清单 |
| `data/updates/2026-10-14.json` | 核实证据、发布时间和排除项 |
| `data/processed/` | 当前分析与forecast.json |
| `data/archive/2026-10-07/` | 优化前完整产物与文档 |
| `tests/test_prediction.py` | 18项关键回归测试 |

旧的 `model_summary.json`、`model_vs_market.csv`、拼写错误的 `anthopic_term_structure.csv`
已归档，避免与当前输出混淆。当前使用baseline_*、final_model_vs_market.csv及forecast.json。

## 交付前仍需完成

- 填入组号、姓名、实际分工和AI使用说明。
- 根据后续可靠公告更新证据；分别核实说明会、公开S-1与首日交易。
- 将当前报告排版成Word或PDF，核对正文页数。
- 结算后计算Brier分数和对数损失；单一事件不足以验证概率校准。
