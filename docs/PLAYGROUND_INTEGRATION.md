# LoomQ Playground 集成说明

## 集成定位

本分支以师姐仓库 `upstream/main` 的提交
`735faff12f9bfbc6376751be255dc15b66c6f4aa` 为底座，在不替换比赛核心代码的前提下，增加了 LoomQ Playground 产品层。

Playground 提供自然语言生成实验、OpenQASM 与电路预览、量子门解释、后端推荐、本地模拟运行和测量结果可视化。比赛正式入口和公开接口保持不变。

## 代码边界

### 独立新增的产品层

- `frontend/`：原生 HTML、CSS 和 JavaScript 前端。
- `product_service.py`：静态页面与 Playground API 服务，负责会话配置、实验生成、运行调用和结果整理。
- `start_playground.bat`：Windows 启动与 Python 运行环境检查。
- `Dockerfile.playground`、`.dockerignore`：Playground 独立容器入口，不替换比赛 evaluator 的 Dockerfile。
- `docs/PLAYGROUND_QUICKSTART.md`：首次使用说明。

### 对比赛核心的必要兼容增量

仅在 `starter_kit/l2/client.py` 增加了 request-scoped LLM 配置入口：

- Playground 可以按浏览器会话使用用户自己的 OpenAI-compatible API。
- 配置通过 `ContextVar` 隔离，请求结束后恢复，不修改全局 `os.environ`。
- CLI 和 evaluator 仍继续读取正式的 `LOOMQ_LLM_BASE_URL`、`LOOMQ_LLM_API_KEY`、`LOOMQ_LLM_MODEL`。
- `adapter.agent_chat(prompt)` 等比赛公开函数签名没有改变。

没有创建第二套 L1/L2/L3，也没有用旧版 `starter_kit/` 覆盖师姐代码。

## 保持不变的正式文件与接口

- `starter_kit/adapter.py` 的公开接口。
- `starter_kit/submission.yaml` 的提交契约。
- `starter_kit/Dockerfile` 的 evaluator 环境。
- L1、L2、L3 的既有业务路径与后端路由。
- SpinQ、OriginQ、Braket 的统一运行结果结构。

Playground 只通过现有 `adapter.agent_chat()` 和 `adapter.run()` 接入比赛能力。

## 主要数据流

```text
浏览器 Prompt
  -> Product Service /api/generate
  -> adapter.agent_chat(prompt)
  -> L2 生成 QASM 或后端推荐
  -> 现有 parser/IR 校验
  -> Circuit/QASM/解释展示

用户选择 backend 与 shots
  -> Product Service /api/run
  -> adapter.run(qasm, target, shots)
  -> 现有 L1 backend
  -> counts 与测量结果展示
```

## LLM 配置优先级与安全边界

```text
当前浏览器会话配置
  > 服务端完整 LOOMQ_LLM_* 环境变量
  > 未配置
```

用户 API Key 仅保存在 Product Service 进程内存中的随机浏览器会话里，不写入源码、Git、日志或 `localStorage`，也不会由配置查询接口返回。服务重启后，会话 Key 自动失效。

## 后续同步 upstream 的原则

1. 始终以新的 `upstream/main` 为底座构造集成版本。
2. 不整体替换 `starter_kit/`，只迁移 Playground 产品增量。
3. 若 upstream 已提供等价能力，优先适配正式接口。
4. 若 `starter_kit/l2/client.py` 同一区域发生变化，应人工审查 request-scoped 配置兼容性，不自动选择 ours/theirs。
5. 每次同步后重新验证 L1、L2、L3，以及 Generate、Circuit、Backend、Run、Measurement 完整链路。

## 启动与验证

首次试玩请参阅 [Playground 快速开始](PLAYGROUND_QUICKSTART.md)。Windows 环境可在仓库根目录运行：

```powershell
start_playground.bat
```

然后访问 `http://127.0.0.1:4173/`。不要直接通过 `file://` 打开 `frontend/index.html`。
