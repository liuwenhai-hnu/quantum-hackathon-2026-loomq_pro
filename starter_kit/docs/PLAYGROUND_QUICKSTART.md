# LoomQ Playground 快速开始

LoomQ Playground 是一个面向量子计算初学者的网页实验台：用自然语言生成 OpenQASM 电路，查看量子门解释，并在 SpinQ、OriginQ 或 AWS Braket 本地模拟器上运行和比较测量结果。

## 方式一：Docker（推荐）

已安装并启动 Docker 后，在仓库根目录执行：

```powershell
docker build -f starter_kit/Dockerfile.playground -t loomq-playground:local starter_kit
docker run --rm -p 4173:4173 loomq-playground:local
```

浏览器访问 `http://127.0.0.1:4173/`，再通过右上角“连接 API”填写自己的 OpenAI-compatible API。Key 不会写入镜像或仓库。

如果服务器已经配置完整的 `LOOMQ_LLM_BASE_URL`、`LOOMQ_LLM_API_KEY` 和 `LOOMQ_LLM_MODEL`，也可传入容器：

```powershell
docker run --rm -p 4173:4173 `
  -e LOOMQ_LLM_BASE_URL="https://api.example.com" `
  -e LOOMQ_LLM_API_KEY="填写你自己的 Key" `
  -e LOOMQ_LLM_MODEL="your-model" `
  loomq-playground:local
```

## 方式二：Windows 一键启动

推荐使用 **Python 3.10**。克隆并解压仓库后，直接双击 `starter_kit` 目录中的：

```text
starter_kit\start_playground.bat
```

首次运行会先征求确认，然后自动创建 `starter_kit/.venv` 并安装 `starter_kit/requirements.txt`。安装完成且 `adapter`、`spinqit`、`pyqpanda`、`braket` 全部通过运行预检后，才会启动 Product Service。第二次双击会直接复用已准备好的 `.venv`。

如果没有找到 Python 3.10、用户取消初始化、依赖安装失败或运行预检不通过，启动器会显示具体原因并停止，不会显示虚假的 Ready 状态。

启动成功后，浏览器会自动打开：

```text
http://127.0.0.1:4173/
```

## 方式三：手动 Python

也可以在已安装依赖的 Python 3.10 环境中手动启动：

```powershell
python -m pip install -r starter_kit\requirements.txt
python starter_kit/product_service.py
```

> 不要直接双击 `starter_kit/frontend/index.html`。静态文件无法连接 Product Service，因此不能生成或运行实验。

## 第一次使用

1. 点击右上角的 **连接 API**。
2. 填写自己的 OpenAI-compatible API，并点击 **测试连接**。
3. 测试成功后点击 **应用**。
4. 选择“量子硬币”“量子纠缠”或“相位干涉”，再点击 **生成实验**。
5. 查看 Circuit/QASM，选择后端和 Shots，然后点击 **Run Experiment**。

DeepSeek 示例：

```text
Base URL: https://api.deepseek.com
Model: deepseek-v4-flash
API Key: 填写你自己的 Key
```

API Key 只保存在当前 Product Service 进程的浏览器会话中，不写入项目文件；服务重启后需要重新填写。

## 切换本地后端

生成实验后，在“推荐运行后端”中展开选择器，可切换：

- SpinQ Taurus
- OriginQ CPUQVM
- AWS Braket LocalSimulator

切换后电路和 QASM 不变，只有实际执行平台与返回结果改变。

## 常见问题

| 现象 | 处理方法 |
|---|---|
| Product Service 未连接 | 确认 `starter_kit/product_service.py` 正在运行，并访问 `http://127.0.0.1:4173/`，不要打开 `file://` 页面。 |
| API 未配置 | 点击右上角“连接 API”，测试并应用自己的配置。 |
| API Key 无效 | 检查 Key 是否复制完整、是否过期，以及是否有模型调用权限。 |
| Model 不存在或无权限 | 使用服务商实际支持的模型名；DeepSeek 示例为 `deepseek-v4-flash`。 |
| Python 依赖缺失 | 重新双击 `starter_kit/start_playground.bat`，确认首次初始化；启动器会创建或补全 `starter_kit/.venv` 并重新执行严格运行预检。 |
