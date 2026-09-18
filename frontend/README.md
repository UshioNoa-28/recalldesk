# RecallDesk Web Console（前端控制台）

基于 **React 19 + TypeScript + Vite + Tailwind CSS + Lucide Icons + Framer Motion** 构建的现代化知识库与向量检索工作台。

---

## 🌟 核心功能特性

1. **📚 知识库管理面板**：
   - 拖拽 / 点击上传文件（支持 `.txt`, `.md`, `.csv`, `.json`, `.pdf`，上限 10MB）。
   - 实时文档列表、切片统计（Chunks）、创建/索引时间、分页与关键词过滤。
   - 任务状态智能轮询（`pending` → `indexing` → `ready` / `failed` 动画指示）。
   - 文档详情与原始 JSON 元数据查看、错误原因分析排查。

2. **🔍 向量相似度检索 (Vector Search)**：
   - 自然语言搜索框，支持常用提问快捷填充与历史记录。
   - `Top K` 滑块实时调整（1 ~ 20 条切片）。
   - 检索耗时计时器（ms）与相似度得分仪表盘（颜色渐变条 + 百分比）。
   - 知识切片代码高亮、长文本展开/收起、一键复制。

3. **💬 RAG 对话问答工作台 (Playground)**：
   - 体验 RAG 端到端检索增强问答过程。
   - 智能展示召回的引用切片来源与匹配度。

4. **📋 后端协作与 CORS 指南**：
   - 内置后端接口清单与交互指引，方便后端同学对接。
   - 快速复制 FastAPI CORS 配置代码片段。

5. **⚡ 开箱即用与跨域兼容**：
   - 配置了 Vite 本地开发代理（`/api` → `http://127.0.0.1:8000`），在后端未配置 CORS 时也可直接调试。
   - 支持在界面右上角随时切换 API Base URL（支持直接连 `http://127.0.0.1:8000` 或自定义地址）。

---

## 🚀 本地启动与运行

```bash
# 进入前端目录
cd frontend

# 安装依赖（推荐使用国内镜像加速）
pnpm install

# 启动本地开发服务 (默认运行在 http://localhost:5173)
pnpm dev

# 构建生产版本
pnpm build
```
