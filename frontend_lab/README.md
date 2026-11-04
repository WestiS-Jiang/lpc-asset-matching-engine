# Frontend Lab

独立前端联调页面（与后端解耦），用于快速验证：

- Prompt -> `/ai/analyze` 的命中效果
- 哪些层是 `LPC 内置`，哪些是 `需AI生成`
- 已命中 LPC 层的叠加预览效果
- Catalog-only 模式下的结构化匹配结果
- 安装 LPC 素材库后的分层组合预览
- 实验性 `GEN` 模式（生图与注册不作为稳定演示主线）

## 启动方式

1. 安装依赖并启动后端（项目根目录）：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

2. 启动静态前端（项目根目录）：

```bash
python3 -m http.server 4173
```

3. 打开：

- `http://127.0.0.1:4173/frontend_lab/index.html`

## 页面逻辑

- 点击 `Analyze` 后：
  - 调用 `POST /ai/analyze`
  - 逐层调用 `GET /assets/lookup/{item_id}` 做来源判定
  - 在“来源拆分”里显示：
    - `LPC内置库`
    - `本地自定义/可能AI生成`
    - `需AI生成`
  - 在 Canvas 合成已命中层进行预览
- 点击来源表中的 `item_id` 可做单素材预览，并可“替换当前层并重绘组合预览”
- 在 `GEN=ON` 下可点击 `Execute (GEN)` 调用 `POST /ai/execute`，查看每条任务的部分成功/失败状态

## 备注

- 预览是“功能测试预览”，并非最终导出流水线。
- 未安装 `generator/` 时仍可展示目录、语义匹配和能力报告，但不显示真实素材图。
- 运行 `scripts/setup_lpc_generator.sh` 后可启用完整 LPC 图片预览。
- 生图和 spritesheet 注册为实验能力，不建议作为面试演示主线。
