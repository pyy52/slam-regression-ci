[English](README.md) | 简体中文

# slam-regression-ci

[![CI](https://github.com/pyy52/slam-regression-ci/actions/workflows/ci.yml/badge.svg)](https://github.com/pyy52/slam-regression-ci/actions/workflows/ci.yml)
[![Metric parity](https://github.com/pyy52/slam-regression-ci/actions/workflows/parity.yml/badge.svg)](https://github.com/pyy52/slam-regression-ci/actions/workflows/parity.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](pyproject.toml)

一个轻量级的 SLAM / 里程计轨迹回归门禁：将候选轨迹与已记录的基线做对比，套用可配置的阈值，当定位精度变差时让 CI 直接失败——同时产出人类可读的 Markdown 报告和机器可读的 JSON 报告。

SLAM 与里程计代码的改动可能在不知不觉中降低精度。[evo](https://github.com/MichaelGrupp/evo) 这类评测工具能算出 ATE/RPE，但回答不了**"这个 PR 是不是回归？"**。为每个仓库手写这套判定策略既繁琐又容易出错。本工具只做这一件事：

```text
基线 JSON（随仓库提交）+ 真值轨迹 + 候选轨迹
        │
        ▼
ATE RMSE / RPE 阈值判定 ──► 退出码 0（通过）或 1（回归）
        │
        ▼
report.md（给人看）+ report.json（给 CI/自动化用）
```

项目处于早期阶段，正在寻找真实使用反馈——欢迎在你的仓库试用，并
[提出 issue](https://github.com/pyy52/slam-regression-ci/issues)。

## 安装

需要 Python 3.8+（兼容 ROS1 Noetic / Ubuntu 20.04），运行时仅依赖 `numpy`
与 `PyYAML`。

```bash
pip install git+https://github.com/pyy52/slam-regression-ci.git@v0.1.0
```

或者不安装直接试用：

```bash
git clone https://github.com/pyy52/slam-regression-ci.git
cd slam-regression-ci && pip install .
```

## 60 秒上手

仓库自带确定性合成示例（圆形轨迹、带小噪声的"好"估计、退化的候选轨迹）：

```bash
# 1) 通过：基线与自身对比（约 0% 变化），退出码 0
slam-regression compare \
  --baseline examples/baseline_metrics.json \
  --reference examples/reference.tum \
  --estimate examples/baseline.tum \
  --config examples/regression.yaml

# 2) 失败：退化候选（ATE +282%），退出码 1
slam-regression compare \
  --baseline examples/baseline_metrics.json \
  --reference examples/reference.tum \
  --estimate examples/candidate_degraded.tum \
  --config examples/regression.yaml \
  --report report.md --json report.json
echo $?
```

用于你自己的项目时，先记录一次基线并提交进仓库：

```bash
# 在你的 SLAM 系统跑出一次已知良好结果之后：
slam-regression record \
  --reference ground_truth.tum \
  --estimate my_slam_output.tum \
  --json baselines/room1_baseline.json
```

之后每次改动都与它对比：

```bash
slam-regression compare \
  --baseline baselines/room1_baseline.json \
  --reference ground_truth.tum \
  --estimate my_slam_output.tum \
  --config regression.yaml \
  --report regression_report.md --json regression_report.json
```

### 示例输出

```text
ATE RMSE:
  baseline:  0.017247 m
  candidate: 0.065853 m
  change: +281.81%
  threshold: +10.00%
RPE translation RMSE:
  baseline:  0.025050 m
  candidate: 0.074284 m
  change: +196.60%
  threshold: +10.00%
STATUS: FAIL
```

退出码：`0` 通过，`1` 回归，`2` 输入/配置错误。

## 配置

```yaml
metrics:
  # 任一已配置规则超限即失败，因此只配置你需要的规则。
  # 相对/绝对规则对改善（负变化）始终放行；max_value 是绝对上限。
  ate_rmse:
    max_relative_regression_percent: 10   # 相对基线的最大增幅（百分比）
    max_absolute_regression: 0.03         # ……且绝对增幅不超过 3 厘米
    # max_value: 0.25                     # 指标本身的绝对上限
  rpe_translation_rmse:
    max_relative_regression_percent: 10

association:
  max_timestamp_diff: 0.01   # 单位秒；每个参考位姿与其"最近"的估计位姿配对

alignment:
  enabled: true              # 用 Umeyama 方法将估计对齐到参考
  correct_scale: false       # 额外估计统一尺度（单目场景）

coverage:
  # 可选门禁：候选实际跟踪到的参考比例（及早发现"只跑了一小段"的假象结果）。
  # 关键帧式估计（ORB-SLAM 等）建议用 min_time_coverage_ratio：关键帧输出
  # 本来就只匹配参考的一小部分位姿（matched_pose_ratio 低是正常的），
  # 但它仍覆盖完整时间线。
  min_matched_pose_ratio: 0.95
  min_time_coverage_ratio: 0.95

rpe_delta: 1                 # 相对位姿误差的帧间隔
```

所有键都可省略：省略 `metrics` 保留默认阈值，省略整个文件则全部使用默认值。
未知键与非法值会被拒绝，并给出可操作的错误信息。基线会记录输入文件的
sha256 指纹；当真值文件被改动、或度量语义设置不一致时，compare 会直接报错
（退出码 2），除非显式指定 `--allow-incompatible-baseline`。

## 作为 CI 门禁用于你的仓库

```yaml
# 你仓库中的 .github/workflows/slam-regression.yml
name: SLAM regression
on: [pull_request]

jobs:
  regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install git+https://github.com/pyy52/slam-regression-ci.git@v0.1.0
      - name: Check trajectory regression
        run: |
          slam-regression compare \
            --baseline baselines/room1_baseline.json \
            --reference data/room1_gt.tum \
            --estimate results/room1_est.tum \
            --config regression.yaml \
            --report regression_report.md --json regression_report.json
      - name: Attach report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: regression-report
          path: |
            regression_report.md
            regression_report.json
```

也可以用一行 Action（本仓库同时是一个 composite action）：

```yaml
      - uses: pyy52/slam-regression-ci@v0.1
        with:
          baseline: baselines/room1_baseline.json
          reference: data/room1_gt.tum
          estimate: results/room1_est.tum
```

提交一次基线 JSON（`baselines/room1_baseline.json`），此后任何让定位变差的
PR 都会失败——并附带一份 Markdown 报告，说明具体是哪个指标恶化了。

不想安装先看看报告长什么样？见[示例报告](docs/sample_report.md)。

## Docker

```bash
docker build -f docker/Dockerfile -t slam-regression-ci .
docker run --rm -v "$PWD/examples:/data" slam-regression-ci compare \
  --baseline /data/baseline_metrics.json \
  --reference /data/reference.tum \
  --estimate /data/candidate_degraded.tum \
  --config /data/regression.yaml
```

## 指标可信度

ATE/RPE 基于 numpy 实现，遵循 TUM RGB-D benchmark 的约定；CI 会在自带示例上
与 [evo](https://github.com/MichaelGrupp/evo)（参考实现）做对拍校验，相对误差
需在 `1e-6` 以内（[对拍工作流](.github/workflows/parity.yml)）。高级评测场景
仍然推荐 evo；本项目刻意保持极简。

## 支持的输入格式

- **TUM 文本文件**：`timestamp tx ty tz qx qy qz qw`（每行一个位姿，允许 `#`
  注释，四元数顺序为 x y z w）——TUM RGB-D benchmark 工具的输出格式，evo 也
  使用该格式。

时间戳关联为**一对一最近邻**：每个参考位姿与其最近的、未被使用的估计位姿
配对（容差 `max_timestamp_diff`）。在真实数据上，配对数与 evo 自身的同步结果
一致；指标可能有微小差异（真实 ORB-SLAM 关键帧数据上 ≤0.3%），源于选对顺序
不同（evo 为每个估计位姿找最近参考位姿，我们为每个参考位姿找最近估计位姿）。
TUM 原版 benchmark 脚本同样是一对一，但取遍历中首个落在容差内的位姿而非最近
的位姿。

## 局限

- 轨迹输入仅支持 TUM 格式（KITTI 位姿在计划中）。
- 指标仅包含 ATE RMSE 与连续帧（`delta = 1`）的 RPE 平移 RMSE；没有分轴细分
  与绘图。
- 基线与特定的真值文件和数据集绑定；更换数据集意味着需要重新记录基线。
- 报告写入文件；还没有 PR 评论机器人。

## Roadmap

- ~~PyPI 包~~ —— [已上架 PyPI](https://pypi.org/project/slam-regression-ci/)
- KITTI 位姿文件支持
- 更多指标（可配置 delta 单位的 RPE、旋转误差）
- 可选的 PR 评论回归摘要
- 基线更新辅助命令（`record --update` 策略）

## 参与贡献

欢迎 issue 与 PR——见 [CONTRIBUTING.md](CONTRIBUTING.md)。说明：本项目日常
工程工作（测试、文档、CI 维护）借助 AI 辅助完成；所有改动都在合并前经过
人工审查。

## 许可证

[MIT](LICENSE)
