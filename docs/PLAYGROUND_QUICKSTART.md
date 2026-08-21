# LoomQ Playground 快速开始

LoomQ Playground 是一个面向量子计算初学者的网页实验台：用自然语言生成 OpenQASM 电路，查看量子门解释，并在 SpinQ、OriginQ 或 AWS Braket 本地模拟器上运行和比较测量结果。

## 方式一：Docker（推荐）

已安装并启动 Docker 后，在仓库根目录执行：

```powershell
docker build -f Dockerfile.playground -t loomq-playground:local .
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

推荐使用 **Python 3.10**。在仓库根目录依次执行：

```powershell
py -3.10 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r starter_kit\requirements.txt
start_playground.bat
```

启动成功后，浏览器会自动打开：

```text
http://127.0.0.1:4173/
```

## 方式三：手动 Python

也可以在已安装依赖的 Python 3.10 环境中手动启动：

```powershell
python -m pip install -r starter_kit\requirements.txt
python product_service.py
```

> 不要直接双击 `frontend/index.html`。静态文件无法连接 Product Service，因此不能生成或运行实验。

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
| Product Service 未连接 | 确认 `product_service.py` 正在运行，并访问 `http://127.0.0.1:4173/`，不要打开 `file://` 页面。 |
| API 未配置 | 点击右上角“连接 API”，测试并应用自己的配置。 |
| API Key 无效 | 检查 Key 是否复制完整、是否过期，以及是否有模型调用权限。 |
| Model 不存在或无权限 | 使用服务商实际支持的模型名；DeepSeek 示例为 `deepseek-v4-flash`。 |
| Python 依赖缺失 | 激活 Python 3.10 环境后重新运行 `python -m pip install -r starter_kit\requirements.txt`。 |
