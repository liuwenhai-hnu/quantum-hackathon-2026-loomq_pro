# LoomQ 人工评分证据

这份文件是人工评分材料的统一入口。请直接编辑它，只填写要申报的项目。截图、原始结果或图表统一放在 `starter_kit/evidence/files/`，也可以引用 `starter_kit/` 中已有的代码和文档。

证据包是可选的。没有申报某项人工分时，留空即可，不影响自动评分。

## 提交前填写

把要申报项目的方框改成 `[x]`，并填写对应内容：

- [ ] L1 真机
- [x] L2 交互体验
- [x] 工程与产品化
- [ ] 自定义量子 RISC-V Bonus
- [x] 新手引导与视觉叙事 Bonus

## L1 真机

每个有效真机平台计 5 分，最多两个平台。模拟器不计真机分。每个平台复制并填写一次下面的信息：

```text
平台名称：[填写]
平台 job ID：[填写]
运行时间：[填写，带时区]
shots：[填写]
实际执行的 QASM：[填写仓库内路径]
平台返回的原始结果：[填写仓库内路径]
任务页截图：[选填，填写仓库内路径]
```

建议把文件放进 `evidence/files/`，比如：

```text
evidence/files/spinq-circuit.qasm
evidence/files/spinq-result.json
evidence/files/spinq-screenshot.png
```

工作人员会核对 job ID、运行时间、电路、shots 和原始结果。截图只能辅助说明，不能代替 job ID 和原始结果。

## L2 交互体验

```text
启动界面或 CLI 的命令：Windows 双击 starter_kit/start_playground.bat；Linux 使用下方 Docker 命令
测试入口或页面地址：http://127.0.0.1:4173/
适合现场体验的 3 个用户任务：
1. 抛一枚量子硬币，让我看看量子如何保留多种可能。
2. 让我看看两个量子比特的纠缠，并解释 H 和 CX 分别做了什么。
3. 生成一个相位干涉实验，解释相位如何通过后续干涉影响测量概率。
截图或演示视频：待审批后补充到 evidence/files/
```

现场体验流程：

1. 双击 `starter_kit/start_playground.bat`。启动器创建或复用 `starter_kit/.venv`，安装依赖并检查 `adapter`、`spinqit`、`pyqpanda`、`braket`。
2. 浏览器打开 `http://127.0.0.1:4173/`。用户在右上角测试并应用自己的 OpenAI-compatible API。API Key 保存在 Product Service 内存中的当前浏览器 session。
3. 用户输入自然语言，或选择量子硬币、量子纠缠、相位干涉。点击 `生成实验` 后，L2 返回 QASM 或后端推荐；QASM 先经过 L1 parser/IR 校验。
4. 页面显示 Circuit、QASM 和步骤解释。用户查看推荐理由，并可切换 SpinQ Taurus、OriginQ CPUQVM、AWS Braket LocalSimulator。后端数据读取 `starter_kit/backend_capabilities.json`。
5. 点击 `Run Experiment` 后，Product Service 调用 `adapter.run(qasm, target, shots)`，展示 backend、shots、耗时、counts、百分比图和 Raw counts。生成新实验时清除旧运行结果。
6. 服务、API、Model、SDK 或运行失败时，页面显示对应错误信息。

详细启动说明见 [`../docs/PLAYGROUND_QUICKSTART.md`](../docs/PLAYGROUND_QUICKSTART.md)。产品层与比赛核心的边界见 [`../docs/PLAYGROUND_INTEGRATION.md`](../docs/PLAYGROUND_INTEGRATION.md)。

Linux Docker 启动：

```bash
docker build -f starter_kit/Dockerfile.playground -t loomq-playground:local starter_kit
docker run --rm -p 4173:4173 loomq-playground:local
```

启动后访问 `http://127.0.0.1:4173/`。

工作人员会在组委会统一模型环境中运行最终代码，测试新手是否看得懂、出错后能否得到有效帮助、结果是否清楚，以及多轮回答是否一致。选手自己的对话截图只用于说明产品流程，不直接证明得分。

## 工程与产品化

已有内容可以直接引用主 README 或其他项目文档，不必复制到本目录。

```text
干净环境中的构建和启动命令：Windows 双击 starter_kit/start_playground.bat；Linux 执行 starter_kit/Dockerfile.playground 的 build/run 命令；完整说明见 starter_kit/docs/PLAYGROUND_QUICKSTART.md
架构说明：见 starter_kit/docs/PLAYGROUND_INTEGRATION.md；主要模块说明见下文
目标用户和使用场景：首次接触量子计算、QASM 或量子 SDK 的学习者与创作者
完整使用流程：自然语言 Prompt → L2 生成/修复 QASM 或推荐后端 → L1 parser/IR 校验 → Circuit/QASM/解释 → 用户选择 Backend 与 shots → adapter.run() → 本地模拟器 → 统一 counts → Measurement 可视化
```

主要模块与边界：

- `starter_kit/frontend/`：HTML/CSS/JavaScript 界面。`api.js` 负责请求，`circuit.js` 绘制电路，`app.js` 管理页面状态和交互。
- `starter_kit/product_service.py`：提供静态页面、`/api/generate`、`/api/run` 和 LLM session 配置接口。
- `starter_kit/adapter.py`：比赛公开入口。Playground 调用 `agent_chat()` 和 `run()`。
- `starter_kit/l1/`：OpenQASM parser、统一 IR、三平台 emitter 与 SpinQ/OriginQ/Braket 本地执行路径。
- `starter_kit/l2/`：模型调用、QASM 生成/修复、后端能力工具、确定性校验与重试。
- `starter_kit/l3/` 与 `starter_kit/riscv_emulator.py`：Hybrid-QASM 解析、经典控制流编译和轻量 RISC-V 执行验证。

可复现性与安全设计：

- Windows 启动器优先复用 `starter_kit/.venv`；环境缺失时，经用户确认后创建该环境并安装 `starter_kit/requirements.txt`。
- Product Service 启动前检查 `adapter` 和三个后端 SDK。界面分别显示平台能力和当前运行环境是否可用。
- LLM 配置优先级为：当前浏览器 session、服务端完整 `LOOMQ_LLM_*`、未配置。session 配置使用 `ContextVar`，请求结束后恢复。
- API Key 不由 GET 接口返回，也不写入前端源码、Git、日志或 `localStorage`。Product Service 重启后 session Key 失效。
- `starter_kit/Dockerfile.playground` 与比赛 `starter_kit/Dockerfile` 相互独立，产品运行入口不会替换 evaluator 容器。
- Playground 的 Run 当前只开放三个本地模拟器。

公开验证入口：

```powershell
.\.venv\Scripts\python.exe starter_kit\evaluator.py --level l1 --target spinq,originq,braket
.\.venv\Scripts\python.exe starter_kit\evaluator.py --level l2
.\.venv\Scripts\python.exe starter_kit\evaluator.py --level l3
```

L2 evaluator 需要由运行者通过环境变量提供完整的 `LOOMQ_LLM_BASE_URL`、`LOOMQ_LLM_API_KEY`、`LOOMQ_LLM_MODEL`。公开 evaluator 通过只代表公开契约自测通过，不等于正式隐藏评测分数。

工作人员会按最终 commit 实际构建和启动，并检查文档与代码是否一致、产品是否真的降低了量子计算的使用门槛。

## 自定义量子 RISC-V Bonus

以下三项必须齐全且测试通过，才获得 8 分：

```text
指令编码规格：[填写文档路径]
模拟器扩展实现：[填写代码路径]
端到端测试命令：[填写命令或文档路径]
```

## 新手引导与视觉叙事 Bonus

```text
零基础首次运行指南：starter_kit/docs/PLAYGROUND_QUICKSTART.md；首页“我完全不懂量子计算，带我体验一次”按钮
量子概念解释：Gate Hover/Click Card、步骤时间线、状态顺序和测量位序说明
结果可视化：真实 counts 柱状图、bitstring/count/百分比 hover、Raw counts、结果与关键 gate 回看联动
错误恢复或无障碍引导：Product Service、API、Model、SDK 和运行错误分别提示；弹层支持 Escape 关闭
```

界面位置：

- 首页提供量子硬币、量子纠缠、相位干涉示例，以及 `我完全不懂量子计算，带我体验一次` 按钮。
- Circuit Preview 直接标出每个 qubit 从 `|0⟩` 开始，并注明量子态顺序 `|q0 q1 ...⟩`。
- Hover 量子门时显示作用对象和简短解释。点击量子门后显示规则、前后状态、当前实验用途和删除该门的影响；数学内容默认折叠。
- 步骤时间线按门的实际位置解释作用。小规模电路的 state trace 由产品层计算；电路过大或无法可靠推导时只显示局部规则。
- Measurement 根据测量前 statevector 显示 0/1 概率、classical bit 写入位置和 counts 位序 `c[n-1]...c0`。
- 结果区显示观测结果、原因和关键公式。`回看 H/CX` 会定位并高亮对应量子门。
- 结果不超过 16 种时显示 bitstring；超过 16 种时显示 `1 的数量分布`，Raw counts 保留完整数据。

建议审批后补充以下截图，文件实际加入仓库后再把“待补”替换为有效链接：

```text
evidence/files/01-home-and-api.png
evidence/files/02-circuit-and-gate-explanation.png
evidence/files/03-backend-selection.png
evidence/files/04-local-run-results.png
evidence/files/05-measurement-explanation.png
```

以上四项各 1 分。普通项目 README 完整不代表自动获得 Bonus。

## 提交规则

- 所有材料都要在截止前进入最终提交的 commit，工作人员不接受截止后补交。
- 外部视频可以用稳定只读链接，源码、原始结果和复现命令应保存在仓库中。
- 整个 fork commit 的归档包不得超过 100 MiB。
- 不要提交 API Key、Token、Cookie、个人身份信息或平台账户隐私。
- 如申报 L1 真机分，在最终提交 Issue 的 `Hardware evidence` 中填写 `starter_kit/evidence/README.md`。
