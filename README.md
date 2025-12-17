# 📚 论文笔记自动化工具 (Paper Watcher)

一个帮助你自动管理论文笔记的工具。当你在Markdown文件中添加论文链接时，它会自动：

1. ✅ 检测新添加的论文链接
2. ✅ 获取论文元数据（标题、作者、年份、会议/期刊）
3. ✅ 从Semantic Scholar获取引用数
4. ✅ 下载PDF到本地
5. ✅ 生成格式化的引用信息

## 安装

```bash
# 安装依赖
pip install watchdog requests

# 或者使用 requirements.txt
pip install -r requirements.txt
```

## 使用方法

### 1. 持续监控模式（推荐）

```bash
python paper_watcher.py --watch ./papers
```

启动后，在 `./papers` 目录下编辑任何 `.md` 文件，添加arXiv链接后保存，工具会自动处理。

### 2. 单次扫描模式

```bash
python paper_watcher.py --watch ./papers --once
```

扫描目录中所有Markdown文件，处理完成后退出。

### 3. 自定义PDF保存目录

```bash
python paper_watcher.py --watch ./papers --pdf-dir ./papers/downloads
```

## 支持的链接格式

目前主要支持 **arXiv** 链接：

```
https://arxiv.org/abs/2301.00001
https://arxiv.org/pdf/2301.00001.pdf
https://arxiv.org/abs/cs.CV/0001234
```

## 使用示例

### 输入（你在Markdown文件中写）：

```markdown
# CNN相关论文

## 经典论文

https://arxiv.org/abs/1512.03385

## 最新研究

https://arxiv.org/abs/2010.11929
```

### 输出（工具自动转换为）：

```markdown
# CNN相关论文

## 经典论文

**Deep Residual Learning for Image Recognition**. Kaiming He, Xiangyu Zhang, Shaoqing Ren et al. arXiv:cs.CV, 2015 ([PDF](pdfs/He_2015_Deep Residual Learning for Image Recognition.pdf)) ([arXiv](https://arxiv.org/abs/1512.03385)) (Citations: 195432)

## 最新研究

**An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale**. Alexey Dosovitskiy, Lucas Beyer, Alexander Kolesnikov et al. arXiv:cs.CV, 2020 ([PDF](pdfs/Dosovitskiy_2020_An Image is Worth 16x16 Words.pdf)) ([arXiv](https://arxiv.org/abs/2010.11929)) (Citations: 42156)
```

## 目录结构

```
papers/
├── CNN.md                          # 你的笔记文件
├── RS.md                           # 遥感相关论文笔记
├── ObjectDetection.md              # 目标检测论文笔记
├── pdfs/                           # 自动下载的PDF
│   ├── He_2015_Deep Residual Learning...pdf
│   └── Dosovitskiy_2020_An Image is Worth...pdf
└── .paper_watcher_state.json       # 状态文件（自动生成）
```

## 常见问题

### Q: 为什么引用数显示为 N/A？
A: Semantic Scholar API可能暂时无法访问，或该论文还未被索引。你可以稍后重新处理。

### Q: 如何重新处理某个链接？
A: 删除 `.paper_watcher_state.json` 文件中对应的记录，然后重新保存Markdown文件。

### Q: 支持Google Scholar链接吗？
A: 目前暂不支持，因为Google Scholar没有公开API。建议使用arXiv链接。

### Q: PDF下载失败怎么办？
A: 检查网络连接，arXiv服务器有时会限速。工具会显示错误信息，你可以稍后重试。

## 进阶用法

### 与Typora配合使用

1. 在Typora中打开你的论文笔记目录
2. 在终端启动 `paper_watcher.py --watch /path/to/your/notes`
3. 在Typora中添加论文链接，保存后自动处理
4. 刷新Typora查看更新后的格式

### 配置为后台服务

可以使用 `nohup` 或 `systemd` 将其配置为后台服务：

```bash
nohup python paper_watcher.py --watch ~/papers > paper_watcher.log 2>&1 &
```

## 反馈与贡献

如果遇到问题或有改进建议，欢迎反馈！

---

祝科研顺利！📖✨
